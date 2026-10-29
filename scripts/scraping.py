"""Scraping helpers for the T&C pipeline — fetching, cleaning and validation.

Kept free of heavy imports (torch, supabase) so it can be unit-tested quickly.
"""
import hashlib
import os
import re
import time

import requests

JINA_PREFIX = "https://r.jina.ai/"

REQUEST_TIMEOUT = 60          # seconds per attempt
MAX_ATTEMPTS = 4
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}

# A legal document shorter than this is almost certainly a wall, not the T&C.
MIN_SOURCE_CHARS = 1_500
# Block-page markers are only trusted on short pages: a long privacy policy may
# legitimately mention "JavaScript" or "captcha".
MARKER_MAX_CHARS = 8_000
BLOCK_MARKERS = re.compile(
    r"enable javascript|javascript is (?:not available|disabled)|log in to (?:continue|facebook|instagram)"
    r"|sign in to continue|verify you are (?:a )?human|captcha|access denied|just a moment"
    r"|attention required|403 forbidden|target url returned error|please enable cookies"
    r"|something went wrong|page not found|iniciar sesi[oó]n para continuar",
    re.IGNORECASE,
)

# New content this much smaller than the current version is treated as a broken scrape.
MAX_SHRINK_RATIO = 0.5


class FetchError(Exception):
    """The source could not be downloaded."""


class InvalidContent(Exception):
    """The source was downloaded but does not look like the real T&C document."""


def real_url(url: str) -> str:
    """Strip the r.jina.ai reader prefix to get the page a human would open."""
    return url[len(JINA_PREFIX):] if url.startswith(JINA_PREFIX) else url


def _headers() -> dict[str, str]:
    headers = {"X-Retain-Images": "none", "User-Agent": "tc-ninja-scraper/1.0"}
    api_key = os.getenv("JINA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def request_delay() -> float:
    """Pause between requests: the anonymous Jina tier allows ~20 requests/minute."""
    return 0.3 if os.getenv("JINA_API_KEY") else 3.2


def fetch_source(url: str, session: requests.Session | None = None, sleep=time.sleep) -> str:
    """Download *url* with timeout and exponential backoff on transient errors."""
    http = session or requests
    last_error = "unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        wait = 2 ** attempt
        try:
            response = http.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_error = f"{type(e).__name__}: {e}"
        else:
            if response.status_code == 200:
                return response.text
            last_error = f"HTTP {response.status_code}"
            if response.status_code not in RETRY_STATUSES:
                break
            retry_after = response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                wait = min(int(retry_after), 60)
        if attempt < MAX_ATTEMPTS:
            sleep(wait)
    raise FetchError(f"{real_url(url)} — {last_error}")


_JINA_HEADER_END = "Markdown Content:"


def strip_jina_header(text: str) -> str:
    """Drop the ``Title / URL Source / Published Time`` preamble Jina prepends.

    Those lines change between runs (timestamps) and are not part of the T&C.
    """
    head = text[:1_500]
    idx = head.find(_JINA_HEADER_END)
    if idx != -1 and head.lstrip().startswith(("Title:", "URL Source:")):
        return text[idx + len(_JINA_HEADER_END):]
    return text


_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()\s]|\([^)]*\))*(?:\s+\"[^\"]*\")?\)")
_SPACES = re.compile(r"[ \t ]+")
_BLANKS = re.compile(r"\n{3,}")


# Cookie-banner buttons that a headless browser captures next to the policy text.
_BANNER_LINES = re.compile(
    r"^(?:accept all|allow all cookies|decline optional cookies|manage data settings|"
    r"aceptar todo|permitir todas las cookies|rechazar cookies opcionales|gestionar configuraci[oó]n de datos)$",
    re.IGNORECASE | re.MULTILINE,
)


def clean_text(raw: str) -> str:
    """Normalise scraped markdown so it is stable across runs and embeds better.

    Removes the Jina preamble, images and link targets (tracking URLs and CDN
    tokens change on every request and would register as a false T&C update).
    """
    text = strip_jina_header(raw).replace("\r\n", "\n")
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BANNER_LINES.sub("", text)
    return _BLANKS.sub("\n\n", text).strip()


def validate_content(text: str, source: str = "") -> None:
    """Raise InvalidContent if *text* looks like a login/bot wall or an error page."""
    if len(text) < MIN_SOURCE_CHARS:
        raise InvalidContent(f"{source} — only {len(text)} chars (expected ≥ {MIN_SOURCE_CHARS})")
    if len(text) < MARKER_MAX_CHARS:
        match = BLOCK_MARKERS.search(text)
        if match:
            raise InvalidContent(f"{source} — looks like a block page ('{match.group(0)}')")


def check_shrink(previous_chars: int | None, new_chars: int) -> None:
    """Raise InvalidContent if the new version is suspiciously smaller than the current one."""
    if previous_chars and new_chars < previous_chars * MAX_SHRINK_RATIO:
        raise InvalidContent(
            f"content shrank from {previous_chars} to {new_chars} chars "
            f"(< {MAX_SHRINK_RATIO:.0%}); use --force if this is legitimate"
        )


def content_hash(text: str) -> str:
    """SHA-256 hex digest of *text*, used for change detection."""
    return hashlib.sha256(text.encode()).hexdigest()


def next_version_tag(today: str, existing: set[str]) -> str:
    """``today`` if free, otherwise ``today.2``, ``today.3`` … (two changes in one day)."""
    if today not in existing:
        return today
    n = 2
    while f"{today}.{n}" in existing:
        n += 1
    return f"{today}.{n}"


_STOPWORDS = {
    "es": frozenset(
        "de la que el en y a los del se las por un para con no una su al lo como más pero sus le ya o este "
        "sí porque esta entre cuando muy sin sobre también me hasta hay donde quien desde todo nos durante "
        "todos uno les ni contra otros ese eso ante ellos e esto mí antes algunos qué unos yo otro otras "
        "otra él tanto esa estos mucho quienes nada muchos cual poco ella estar estas algunas algo nosotros "
        "es son puede datos usuario información servicio".split()
    ),
    "en": frozenset(
        "the of and to in a is that for it as was with be by on not he this are or his from at which but "
        "have an had they you were their one all we can her has there been if more when will would who so "
        "no your may any our such these other than into them only its also use information service data "
        "terms".split()
    ),
}
_WORD = re.compile(r"[a-záéíóúüñ]+", re.IGNORECASE)
LANG_SAMPLE_CHARS = 5_000
LANG_MIN_WORDS = 50
LANG_MIN_RATIO = 1.5  # winner must have >= 1.5x the stopword hits of the runner-up


def detect_language(text: str) -> str | None:
    """Return 'es' or 'en' from a stopword-ratio heuristic, or None if inconclusive."""
    words = [w.lower() for w in _WORD.findall(text[:LANG_SAMPLE_CHARS])]
    if len(words) < LANG_MIN_WORDS:
        return None
    # Words shared by both lists ("a", "no") carry no signal.
    shared = _STOPWORDS["es"] & _STOPWORDS["en"]
    hits = {
        lang: sum(1 for w in words if w in sw and w not in shared)
        for lang, sw in _STOPWORDS.items()
    }
    (best, top), (_, second) = sorted(hits.items(), key=lambda kv: -kv[1])
    if top / len(words) < 0.05 or top < second * LANG_MIN_RATIO:
        return None
    return best
