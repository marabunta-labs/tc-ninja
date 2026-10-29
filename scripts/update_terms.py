"""T&C Ninja — scrape, embed and version the platforms' Terms & Conditions.

For every (platform, language) in ``frontend/config/shared.json``:

1. Download every source through its fetcher chain (Jina → direct → headless
   browser), clean it and validate it is the real document in the right language
   (not a login wall or error page).
2. Compare the content hash with the **current** version. Unchanged → nothing to do.
3. Changed → insert the new version as ``pending``, then promote it to
   ``current`` atomically. The previous current version is **deprecated**
   (``superseded``): searches no longer return it, only version comparisons do.
   A sentence-level diff (plus an optional Gemini summary) is stored with the
   new version, so "what changed?" has a precise answer.
4. Purge superseded versions beyond ``MAX_VERSIONS_TO_KEEP``.

A failed scrape never touches the stored data, and the process exits non-zero
so the scheduled GitHub Action turns red instead of silently going stale.
"""
import os
import sys
import json
import argparse
import datetime
import functools
import math
import time
from pathlib import Path

from dotenv import load_dotenv

from changes import build_changes
from chunking import chunk_document
from fetchers import chain_for, fetch_source_text
from scraping import (
    FetchError,
    InvalidContent,
    check_shrink,
    content_hash,
    next_version_tag,
    real_url,
)

load_dotenv()

_config_path = Path(__file__).parent.parent / "frontend" / "config" / "shared.json"
_config = json.loads(_config_path.read_text())
PLATFORMS = _config["platforms"]
EMBEDDING = _config["embedding"]  # shared with the backend: model, prefixes, dimensions

# Versions kept per (platform, language): the current one plus the previous ones
# (needed for "what changed?" comparisons). Older ones are deleted.
MAX_VERSIONS_TO_KEEP = 3

INSERT_BATCH = 50
PAGE_SIZE = 1000  # Supabase returns at most 1000 rows per request


@functools.lru_cache(maxsize=1)
def get_supabase():
    from supabase import create_client

    from supabase import ClientOptions

    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"], options=ClientOptions(schema="tcninja"))


EMBED_BATCH = 50      # texts per Gemini request
EMBED_RETRIES = 8     # on rate limits (429) / transient errors, waiting 5 s, 10 s, 20 s... (max 65 s)


@functools.lru_cache(maxsize=1)
def get_gemini():
    from google import genai

    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def l2_normalize(vector: list[float]) -> list[float]:
    """Gemini only returns unit-length vectors at full size; the truncated 384-d ones must be normalised by hand."""
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def embed_chunks(texts: list[str]) -> list[list[float]]:
    """Embed passages exactly like the backend embeds queries (same model, dimensions, L2 normalisation)."""
    from google.genai import errors, types

    config = types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=EMBEDDING["dimensions"])
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        batch = texts[start:start + EMBED_BATCH]
        for attempt in range(EMBED_RETRIES):
            try:
                response = get_gemini().models.embed_content(model=EMBEDDING["model"], contents=batch, config=config)
                break
            except errors.APIError as e:
                if e.code not in (429, 500, 503) or attempt == EMBED_RETRIES - 1:
                    raise
                wait = min(65, 5 * 2 ** attempt)
                print(f"   Gemini {e.code} while embedding, retrying in {wait}s...")
                time.sleep(wait)
        if len(response.embeddings) != len(batch):
            raise RuntimeError(f"Gemini returned {len(response.embeddings)} embeddings for {len(batch)} texts")
        vectors.extend(l2_normalize(list(e.values)) for e in response.embeddings)
    return vectors


def get_current_version(platform: str, lang: str) -> dict | None:
    """Return the ``current`` document_versions row for this pair, or None."""
    resp = (
        get_supabase().table("document_versions")
        .select("*")
        .eq("platform", platform)
        .eq("language", lang)
        .eq("status", "current")
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def discard_pending(platform: str, lang: str) -> None:
    """Remove leftovers of an interrupted run (chunks go with them via ON DELETE CASCADE)."""
    get_supabase().table("document_versions").delete() \
        .eq("platform", platform).eq("language", lang).eq("status", "pending").execute()


def purge_old_versions(platform: str, lang: str) -> None:
    """Delete superseded versions beyond MAX_VERSIONS_TO_KEEP (current included)."""
    resp = (
        get_supabase().table("document_versions")
        .select("id, version")
        .eq("platform", platform)
        .eq("language", lang)
        .eq("status", "superseded")
        .order("id", desc=True)
        .execute()
    )
    for old in (resp.data or [])[MAX_VERSIONS_TO_KEEP - 1:]:
        get_supabase().table("document_versions").delete().eq("id", old["id"]).execute()
        print(f"🗑  Purged old version {old['version']} of {platform} ({lang.upper()})")


def taken_version_tags(platform: str, lang: str, prefix: str) -> set[str]:
    resp = (
        get_supabase().table("document_versions")
        .select("version")
        .eq("platform", platform)
        .eq("language", lang)
        .like("version", f"{prefix}%")
        .execute()
    )
    return {r["version"] for r in (resp.data or [])}


def download_sources(platform: dict, lang: str) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """Fetch, clean and validate every source through its fetcher chain.

    Returns ``(sources, language_mismatches, fetchers_used)``. Raises FetchError or
    InvalidContent when any source cannot be obtained: a partial document would
    silently drop a whole policy from the new version.
    """
    sources, mismatched, used = [], [], []
    for url in platform["scrapeUrls"][lang]:
        source = real_url(url)
        fetched = fetch_source_text(url, lang, chain_for(platform, url))
        if not fetched.language_ok:
            mismatched.append(source)
            print(f"⚠️  {source} is in '{fetched.detected_language}', not '{lang}' (no localized page found).")
        sources.append((source, fetched.text))
        used.append(f"{source} via {fetched.fetcher}")
    return sources, mismatched, used


def process_platform_lang(platform: dict, lang: str, force: bool = False) -> str:
    """Bring one platform/language up to date. Returns ``updated``, ``unchanged`` or ``failed``."""
    name = platform["id"]
    label = f"{name} ({lang.upper()})"
    print(f"🥷 Ninja analyzing: {label} — {len(platform['scrapeUrls'][lang])} source(s)...")

    try:
        sources, mismatched, used = download_sources(platform, lang)
    except (FetchError, InvalidContent) as e:
        print(f"❌ {label}: {e}. Stored data left untouched.")
        return "failed"

    combined = "\n\n".join(text for _, text in sources)
    new_hash = content_hash(combined)
    source_hashes = {url: content_hash(text) for url, text in sources}

    current = get_current_version(name, lang)
    if current and current["content_hash"] == new_hash and not force:
        print(f"⏭  {label} unchanged (version {current['version']}).")
        return "unchanged"

    if current and not force:
        try:
            check_shrink((current.get("stats") or {}).get("chars"), len(combined))
        except InvalidContent as e:
            print(f"❌ {label}: {e}. Stored data left untouched.")
            return "failed"
        changed = [u for u, h in source_hashes.items() if (current.get("source_hashes") or {}).get(u) != h]
        print(f"🔄 {label} changed since {current['version']}: {', '.join(changed) or 'source list'}")

    chunks = []  # (source_url, Chunk)
    for url, text in sources:
        chunks.extend((url, c) for c in chunk_document(text))

    print(f"   embedding {len(chunks)} chunks...")
    embeddings = embed_chunks([c.embed_text for _, c in chunks])

    changes = None
    if current:
        changes = build_changes(current.get("full_text"), combined, current["version"], name, lang)
        if changes.get("summary"):
            print(f"   changes vs {current['version']}: +{changes['added']} / -{changes['removed']} sentences")

    today = datetime.date.today().strftime("%Y-%m-%d")
    version = next_version_tag(today, taken_version_tags(name, lang, today))
    sb = get_supabase()

    discard_pending(name, lang)
    version_id = None
    try:
        version_id = sb.table("document_versions").insert({
            "platform": name,
            "language": lang,
            "version": version,
            "status": "pending",
            "content_hash": new_hash,
            "source_hashes": source_hashes,
            "embedding_model": EMBEDDING["id"],
            "full_text": combined,
            "changes": changes,
            "stats": {
                "chunks": len(chunks),
                "chars": len(combined),
                "sources": len(sources),
                "fetchers": used,
                "language_mismatch": mismatched,
            },
        }).execute().data[0]["id"]

        rows = [
            {
                "platform": name,
                "language": lang,
                "content": chunk.content,
                "embedding": emb,
                "version_id": version_id,
                "metadata": {
                    "chunk_index": i,
                    "section": chunk.section,
                    "source_url": url,
                    "fetch_date": today,
                    "version": version,
                    "content_hash": new_hash,
                },
            }
            for i, ((url, chunk), emb) in enumerate(zip(chunks, embeddings))
        ]
        for start in range(0, len(rows), INSERT_BATCH):
            sb.table("documents").insert(rows[start:start + INSERT_BATCH]).execute()

        # Atomic swap: the new version becomes current, the old one is deprecated.
        sb.rpc("activate_document_version", {"p_version_id": version_id}).execute()
    except Exception as e:
        print(f"❌ {label}: storing version {version} failed ({e}). Rolling back.")
        if version_id is not None:
            try:
                sb.table("document_versions").delete().eq("id", version_id).execute()
            except Exception as cleanup_error:
                print(f"⚠️  rollback failed, pending version {version_id} will be cleaned next run: {cleanup_error}")
        return "failed"

    deprecated = f", deprecated {current['version']}" if current else ""
    print(f"✅ {label} → version {version} ({len(chunks)} chunks{deprecated}).")
    purge_old_versions(name, lang)
    return "updated"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scrape and embed T&C documents into Supabase.")
    parser.add_argument(
        "--platform",
        default=None,
        metavar="ID",
        help="Platform ID to update (e.g. Instagram). Omit to update all platforms.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Store a new version even if the content hash is unchanged or the text shrank a lot.",
    )
    args = parser.parse_args(argv)

    platforms_to_run = PLATFORMS
    if args.platform:
        platforms_to_run = [p for p in PLATFORMS if p["id"] == args.platform]
        if not platforms_to_run:
            valid = [p["id"] for p in PLATFORMS]
            print(f"❌ Unknown platform: '{args.platform}'. Valid options: {valid}")
            return 1

    results: dict[str, list[str]] = {"updated": [], "unchanged": [], "failed": []}
    for platform in platforms_to_run:
        for lang in platform["scrapeUrls"]:
            outcome = process_platform_lang(platform, lang, force=args.force)
            results[outcome].append(f"{platform['id']}/{lang}")

    print(
        f"\nSummary: {len(results['updated'])} updated, "
        f"{len(results['unchanged'])} unchanged, {len(results['failed'])} failed."
    )
    if results["failed"]:
        print("Failed: " + ", ".join(results["failed"]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
