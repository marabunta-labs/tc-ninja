"""Fallback chain of fetchers (jina -> direct -> playwright) with language verification.

Optional dependencies (trafilatura, playwright + chromium) are imported lazily:
a fetcher whose dependency is missing is skipped with a clear message.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

import scraping
from scraping import FetchError, InvalidContent

log = logging.getLogger(__name__)

DEFAULT_CHAIN = ["jina", "direct", "playwright"]

LOCALES = {"es": "es-ES", "en": "en-US"}
ACCEPT_LANGUAGE = {"es": "es-ES,es;q=0.9,en;q=0.3", "en": "en-US,en;q=0.9"}
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class FetcherUnavailable(Exception):
    """A fetcher's optional dependency (library or browser) is not installed."""


@dataclass
class Fetched:
    text: str                      # cleaned and validated
    fetcher: str
    language_ok: bool
    detected_language: str | None


def _language_cookies(url: str, lang: str) -> list[dict]:
    host = urlparse(url).hostname or ""
    cookies = []
    if host.endswith("youtube.com") or host.endswith("google.com"):
        gl = "ES" if lang == "es" else "US"
        cookies.append({"name": "PREF", "value": f"hl={lang}&gl={gl}", "domain": "." + ".".join(host.split(".")[-2:]), "path": "/"})
    if host.endswith("telegram.org"):
        cookies.append({"name": "stel_ln", "value": lang, "domain": "telegram.org", "path": "/"})
    return cookies


def _extract(html: str) -> str:
    try:
        import trafilatura
    except ImportError as e:
        raise FetcherUnavailable("trafilatura not installed (uv add trafilatura)") from e
    text = trafilatura.extract(
        html, output_format="markdown", include_links=False, include_images=False,
        include_tables=True, favor_recall=True,
    )
    return text or ""


# ---- individual fetchers: (url, lang) -> raw text -------------------------------

def _fetch_jina(url: str, lang: str) -> str:
    import time
    text = scraping.fetch_source(scraping.JINA_PREFIX + scraping.real_url(url))
    time.sleep(scraping.request_delay())
    return text


def _fetch_direct(url: str, lang: str) -> str:
    _extract("<html></html>")  # dependency check
    real = scraping.real_url(url)
    cookies = {c["name"]: c["value"] for c in _language_cookies(real, lang)}
    try:
        r = requests.get(
            real, timeout=scraping.REQUEST_TIMEOUT, cookies=cookies,
            headers={"User-Agent": BROWSER_UA, "Accept-Language": ACCEPT_LANGUAGE[lang]},
        )
    except requests.RequestException as e:
        raise FetchError(f"{type(e).__name__}: {e}") from e
    if r.status_code != 200:
        raise FetchError(f"HTTP {r.status_code}")
    return _extract(r.text)


_EXPAND_JS = """
() => {
  let n = 0;
  document.querySelectorAll('details:not([open])').forEach(d => { d.open = true; n++; });
  document.querySelectorAll('[aria-expanded="false"]').forEach(el => { try { el.click(); n++; } catch (e) {} });
  const re = /^\\s*(show more|see more|read more|view more|expand( all)?|ver m[aá]s|mostrar m[aá]s|leer m[aá]s|ampliar)\\s*$/i;
  document.querySelectorAll('button, [role="button"], a[href="#"]').forEach(el => {
    if (re.test(el.innerText || '')) { try { el.click(); n++; } catch (e) {} }
  });
  return n;
}
"""


def _fetch_playwright(url: str, lang: str) -> str:
    try:
        from playwright.sync_api import Error as PWError
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise FetcherUnavailable("playwright not installed (uv add playwright)") from e
    real = scraping.real_url(url)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except PWError as e:
            raise FetcherUnavailable(f"chromium not available (uv run playwright install chromium): {str(e).splitlines()[0]}") from e
        try:
            ctx = browser.new_context(
                locale=LOCALES[lang], user_agent=BROWSER_UA,
                extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE[lang]},
            )
            cookies = _language_cookies(real, lang)
            if cookies:
                ctx.add_cookies(cookies)
            page = ctx.new_page()
            try:
                page.goto(real, wait_until="domcontentloaded", timeout=60_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except PWError:
                    pass
                last_len = -1
                for _ in range(8):  # expand + scroll until the page stops growing
                    page.evaluate(_EXPAND_JS)
                    for _ in range(6):
                        page.mouse.wheel(0, 4000)
                        page.wait_for_timeout(250)
                    page.wait_for_timeout(500)
                    length = page.evaluate("document.body ? document.body.innerText.length : 0")
                    if length == last_len:
                        break
                    last_len = length
                html = page.content()
            except PWError as e:
                raise FetchError(f"{type(e).__name__}: {str(e).splitlines()[0]}") from e
        finally:
            browser.close()
    return _extract(html)


FETCHERS = {"jina": _fetch_jina, "direct": _fetch_direct, "playwright": _fetch_playwright}


def chain_for(platform_cfg: dict, url: str) -> list[str] | None:
    """Per-source override from a platform's ``sourceFetchers`` (keyed by real URL), else None."""
    chain = (platform_cfg.get("sourceFetchers") or {}).get(scraping.real_url(url))
    return list(chain) if chain else None


def fetch_source_text(url: str, lang: str, fetchers: list[str] | None = None) -> Fetched:
    """Try each fetcher in order; first valid + right-language result wins.

    Falls back to the best valid (longest) result with ``language_ok=False`` if
    none matches *lang*; raises FetchError listing every failure if none is valid.
    """
    chain = fetchers or DEFAULT_CHAIN
    failures: list[str] = []
    valid: list[Fetched] = []
    for name in chain:
        fn = FETCHERS.get(name)
        if fn is None:
            failures.append(f"{name}: unknown fetcher")
            continue
        try:
            text = scraping.clean_text(fn(url, lang))
            scraping.validate_content(text, scraping.real_url(url))
        except FetcherUnavailable as e:
            failures.append(f"{name}: skipped — {e}")
            log.warning("fetcher %s skipped: %s", name, e)
            continue
        except (FetchError, InvalidContent) as e:
            failures.append(f"{name}: {e}")
            continue
        except Exception as e:  # a buggy fetcher must not abort the chain
            failures.append(f"{name}: {type(e).__name__}: {e}")
            continue
        detected = scraping.detect_language(text)
        ok = detected is None or detected == lang
        result = Fetched(text, name, ok, detected)
        if ok:
            return result
        failures.append(f"{name}: language mismatch (expected {lang}, got {detected})")
        valid.append(result)
    if valid:
        return max(valid, key=lambda f: len(f.text))
    raise FetchError(f"{scraping.real_url(url)} — all fetchers failed: " + "; ".join(failures))
