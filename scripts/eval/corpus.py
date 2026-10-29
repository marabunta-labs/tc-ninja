"""Local, disk-cached copy of the T&C corpus for offline retrieval evaluation.

No Supabase needed: documents are scraped (same cleaning as production) and
cached under eval/.cache so experiments are fast and reproducible.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraping import clean_text, fetch_source, real_url, request_delay  # noqa: E402

CACHE = Path(__file__).parent / ".cache"
CONFIG = Path(__file__).parent.parent.parent / "frontend" / "config" / "shared.json"


def load_platforms() -> dict:
    return {p["id"]: p for p in json.loads(CONFIG.read_text())["platforms"]}


def _path(url: str) -> Path:
    safe = "".join(c if c.isalnum() else "_" for c in real_url(url))[:150]
    return CACHE / f"{safe}.txt"


def get_source(url: str) -> str:
    """Cleaned text of one source, downloaded once and cached."""
    path = _path(url)
    if not path.exists():
        CACHE.mkdir(exist_ok=True)
        time.sleep(request_delay())
        path.write_text(clean_text(fetch_source(url)))
    return path.read_text()


def get_documents(platform: str, lang: str) -> list[tuple[str, str]]:
    """[(real_url, text)] for one platform/language."""
    urls = load_platforms()[platform]["scrapeUrls"][lang]
    docs = []
    for u in urls:
        try:
            docs.append((real_url(u), get_source(u)))
        except Exception as e:  # flaky sources (e.g. X 403): evaluate with what we have
            print(f"  skipped {real_url(u)}: {e}", file=sys.stderr)
    return docs


if __name__ == "__main__":
    langs = sys.argv[1:] or ["en"]
    for pid, p in load_platforms().items():
        for lang in langs:
            for url, text in get_documents(pid, lang):
                print(f"{pid:10} {lang} {len(text):7d}  {url}")
