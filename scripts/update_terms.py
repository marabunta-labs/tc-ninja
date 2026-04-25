import os
import json
import hashlib
import requests
import datetime
from pathlib import Path
from sentence_transformers import SentenceTransformer
from supabase import create_client
from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

_config_path = Path(__file__).parent.parent / "frontend" / "config" / "shared.json"
PLATFORMS = json.loads(_config_path.read_text())["platforms"]

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase = create_client(supabase_url, supabase_key)

model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

# How many past versions to keep per (platform, language). Older ones are deleted.
MAX_VERSIONS_TO_KEEP = 2

def get_chunks(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
    """Split *text* into overlapping chunks suitable for embedding."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    return splitter.split_text(text)


def purge_old_versions(platform_name: str, platform_lang: str) -> None:
    """Delete rows older than MAX_VERSIONS_TO_KEEP for this (platform, language)."""
    resp = (
        supabase.table("documents")
        .select("metadata->>version")
        .eq("platform", platform_name)
        .eq("language", platform_lang)
        .execute()
    )
    versions = sorted(
        {r.get("version") for r in (resp.data or []) if r.get("version")},
        reverse=True,
    )
    # versions is ordered newest→oldest; skip the ones we want to keep
    versions_to_delete = versions[MAX_VERSIONS_TO_KEEP:]
    for ver in versions_to_delete:
        supabase.table("documents") \
            .delete() \
            .eq("platform", platform_name) \
            .eq("language", platform_lang) \
            .eq("metadata->>version", ver) \
            .execute()
        print(f"🗑  Deleted old version {ver} for {platform_name} ({platform_lang.upper()})")


def content_hash(text: str) -> str:
    """Return the SHA-256 hex digest of *text*, used for change detection."""
    return hashlib.sha256(text.encode()).hexdigest()


def get_latest_version(platform_name: str, platform_lang: str) -> str | None:
    """Return the most recent version tag stored for this (platform, language), or None."""
    resp = (
        supabase.table("documents")
        .select("metadata->>version")
        .eq("platform", platform_name)
        .eq("language", platform_lang)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0].get("version")
    return None


def get_latest_hash(platform_name: str, platform_lang: str) -> str | None:
    """Return the content_hash stored in the most recent version, or None."""
    resp = (
        supabase.table("documents")
        .select("metadata")
        .eq("platform", platform_name)
        .eq("language", platform_lang)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    if resp.data:
        return resp.data[0].get("metadata", {}).get("content_hash")
    return None


def process_platform_lang(name: str, urls: list[str], lang: str) -> None:
    """Fetch, embed, and store all T&C documents for one platform/language pair.

    Two-level skip logic to avoid redundant work:

    1. **Version-date fast-path** (no network): if today's version is already
       stored in the DB, return immediately without fetching any URL.
    2. **Content-hash check** (after fetch): if the fetched content is byte-for-byte
       identical to the last stored version (combined hash across all sources),
       skip the insert even when running on a new calendar day.

    Otherwise splits each document into chunks, embeds them, bulk-inserts into
    Supabase (preserving per-chunk ``source_url``), and purges old versions.
    """
    current_version = datetime.date.today().strftime("%Y-%m-%d")

    # Fast-path: today's version is already stored — no network requests needed
    if get_latest_version(name, lang) == current_version:
        print(f"⏭  {name} ({lang.upper()}) already at version {current_version}, skipping.")
        return

    print(f"🥷 Ninja analyzing: {name} ({lang.upper()}) — {len(urls)} source(s)...")

    fetched: list[tuple[str, str]] = []
    for url in urls:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"❌ Error accessing {url} ({name} {lang.upper()})")
            return
        fetched.append((url, response.text))

    # Secondary check: skip if content hasn't changed since the last stored version
    combined_text = "\n\n".join(text for _, text in fetched)
    new_hash = content_hash(combined_text)

    if get_latest_hash(name, lang) == new_hash:
        print(f"⏭  {name} ({lang.upper()}) content unchanged, skipping.")
        return

    rows = []
    chunk_index = 0
    for url, text in fetched:
        for chunk in get_chunks(text):
            embedding = model.encode(chunk).tolist()
            rows.append({
                "platform": name,
                "language": lang,
                "content": chunk,
                "embedding": embedding,
                "metadata": {
                    "chunk_index": chunk_index,
                    "source_url": url,
                    "fetch_date": current_version,
                    "version": current_version,
                    "content_hash": new_hash,
                },
            })
            chunk_index += 1

    # Bulk insert in batches to avoid request size limits
    BATCH = 50
    for start in range(0, len(rows), BATCH):
        supabase.table("documents").insert(rows[start:start + BATCH]).execute()

    print(f"✅ {name} ({lang.upper()}) updated ({len(rows)} chunks from {len(urls)} source(s), version {current_version}).")

    # Clean up old versions so the DB doesn't grow unbounded
    purge_old_versions(name, lang)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape and embed T&C documents into Supabase.")
    parser.add_argument(
        "--platform",
        default=None,
        metavar="ID",
        help="Platform ID to update (e.g. Instagram). Omit to update all platforms.",
    )
    args = parser.parse_args()

    platforms_to_run = PLATFORMS
    if args.platform:
        platforms_to_run = [p for p in PLATFORMS if p["id"] == args.platform]
        if not platforms_to_run:
            valid = [p["id"] for p in PLATFORMS]
            print(f"❌ Unknown platform: '{args.platform}'. Valid options: {valid}")
            raise SystemExit(1)

    for platform in platforms_to_run:
        name = platform["id"]
        for lang, urls in platform["scrapeUrls"].items():
            process_platform_lang(name, urls, lang)