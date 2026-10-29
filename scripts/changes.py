"""What changed between two versions of a T&C document.

Sentence-level set diff (robust to reformatting and to pages that come back as a
single line), plus an optional Gemini summary written in the document's language.
"""
import os
import re
import time

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+|\n+")
_MIN_SENTENCE_CHARS = 40
# If this share of the new text is "added", the page was restructured (different
# fetcher / site redesign), not edited: a summary would be noise.
RESTRUCTURED_RATIO = 0.6
MAX_LISTED = 25
MAX_SENTENCE_CHARS = 400

SUMMARY_PROMPT = """You compare two versions of the Terms & Conditions / Privacy Policy of {platform}.
Below are sentences REMOVED from the old version and sentences ADDED in the new one.

Write a concise changelog for a non-lawyer, in {language}:
- At most 8 bullet points, each one sentence, focused on what matters to the user (data collected or shared, rights, licences, deletion, age, fees, AI use, disputes).
- Ignore pure wording, formatting or renumbering changes.
- If the differences are only cosmetic, answer exactly: NO_MATERIAL_CHANGES
- Use ONLY the sentences below; never invent changes.

REMOVED:
{removed}

ADDED:
{added}
"""

_LANGUAGE_NAMES = {"es": "Spanish", "en": "English"}


def _norm(sentence: str) -> str:
    text = re.sub(r"[*_#>`]", "", sentence.lower().replace("’", "'"))
    return re.sub(r"\s+", " ", text).strip(" -.,;:!?")


def sentences(text: str) -> list[str]:
    """Sentence-like units, long enough to be meaningful (keeps original casing)."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if len(s.strip()) >= _MIN_SENTENCE_CHARS]


def diff_versions(old_text: str, new_text: str) -> dict:
    """Sentences removed from / added to the text, plus counts. Order-insensitive."""
    old = {_norm(s): s for s in sentences(old_text)}
    new = {_norm(s): s for s in sentences(new_text)}
    added = [new[k] for k in new if k not in old]
    removed = [old[k] for k in old if k not in new]
    return {
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
        "restructured": bool(new) and len(added) / len(new) >= RESTRUCTURED_RATIO,
    }


def _bullets(items: list[str]) -> str:
    shown = [f"- {s[:MAX_SENTENCE_CHARS]}" for s in items[:MAX_LISTED]]
    if len(items) > MAX_LISTED:
        shown.append(f"- (... and {len(items) - MAX_LISTED} more)")
    return "\n".join(shown) or "- (none)"


def summarise_changes(diff: dict, platform: str, lang: str, client=None, model: str | None = None) -> str | None:
    """Gemini changelog for *diff*, or None (no key, cosmetic change, or API failure)."""
    if not (diff["added"] or diff["removed"]) or diff["restructured"]:
        return None
    if client is None:
        if not os.getenv("GEMINI_API_KEY"):
            return None
        from google import genai

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = model or os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
    prompt = SUMMARY_PROMPT.format(
        platform=platform,
        language=_LANGUAGE_NAMES.get(lang, "English"),
        removed=_bullets(diff["removed"]),
        added=_bullets(diff["added"]),
    )
    for attempt in range(3):
        try:
            text = (client.models.generate_content(model=model, contents=prompt).text or "").strip()
            return None if not text or text == "NO_MATERIAL_CHANGES" else text
        except Exception as e:  # 503 "high demand" is common: back off and retry
            if attempt == 2:
                print(f"⚠️  change summary failed for {platform} ({lang}): {e}")
                return None
            time.sleep(2 ** (attempt + 1))
    return None


def build_changes(old_text: str | None, new_text: str, previous_version: str, platform: str, lang: str,
                  client=None, model: str | None = None) -> dict:
    """The ``document_versions.changes`` payload for a new version."""
    if not old_text:
        return {"previous_version": previous_version, "note": "previous text was not stored, no diff available"}
    diff = diff_versions(old_text, new_text)
    changes = {
        "previous_version": previous_version,
        "added": diff["added_count"],
        "removed": diff["removed_count"],
        "restructured": diff["restructured"],
    }
    summary = summarise_changes(diff, platform, lang, client, model)
    if summary:
        changes["summary"] = summary
    return changes
