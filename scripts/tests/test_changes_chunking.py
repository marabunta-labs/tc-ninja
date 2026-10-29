from unittest.mock import MagicMock

import changes
from changes import build_changes, diff_versions, summarise_changes
from chunking import chunk_document

OLD = (
    "We keep your data for twelve months after you close the account. "
    "You may delete your content at any time from settings. "
    "We never share your contacts with advertisers under any circumstance."
)
NEW = (
    "We keep your data for thirty days after you close the account. "
    "You may delete your content at any time from settings. "
    "We never share your contacts with advertisers under any circumstance. "
    "We may use your posts to train artificial intelligence models."
)


class TestDiff:
    def test_finds_added_and_removed_sentences(self):
        d = diff_versions(OLD, NEW)
        assert d["added_count"] == 2 and d["removed_count"] == 1
        assert any("thirty days" in s for s in d["added"])
        assert any("twelve months" in s for s in d["removed"])
        assert not d["restructured"]

    def test_ignores_formatting_and_order(self):
        parts = [p for p in OLD.split(". ") if p]
        reordered = ". ".join(reversed(parts))
        assert diff_versions(OLD, OLD.replace("We keep", "**We keep**"))["added_count"] == 0
        assert diff_versions(OLD, reordered)["added_count"] == 0
        assert diff_versions(OLD, OLD)["removed_count"] == 0

    def test_single_line_documents_work(self):
        assert diff_versions(OLD.replace(". ", ".  "), NEW)["added_count"] == 2

    def test_completely_different_text_is_restructured(self):
        other = "Completely different wording about unrelated topics appears in this new document. " * 1
        other += "Another long sentence that shares nothing with the previous document at all here."
        assert diff_versions(OLD, other)["restructured"]


class TestChangesPayload:
    def test_no_previous_text(self):
        c = build_changes(None, NEW, "2026-01-01", "TikTok", "en")
        assert "note" in c and c["previous_version"] == "2026-01-01"

    def test_summary_from_llm(self):
        client = MagicMock()
        client.models.generate_content.return_value = MagicMock(text="- Retention cut to 30 days")
        c = build_changes(OLD, NEW, "2026-01-01", "TikTok", "en", client=client, model="m")
        assert c["summary"] == "- Retention cut to 30 days" and c["added"] == 2
        prompt = client.models.generate_content.call_args.kwargs["contents"]
        assert "thirty days" in prompt and "English" in prompt

    def test_cosmetic_answer_has_no_summary(self):
        client = MagicMock()
        client.models.generate_content.return_value = MagicMock(text="NO_MATERIAL_CHANGES")
        assert "summary" not in build_changes(OLD, NEW, "v", "X", "en", client=client)

    def test_no_api_key_means_no_summary(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert summarise_changes(diff_versions(OLD, NEW), "X", "en") is None

    def test_api_failure_is_not_fatal(self, monkeypatch):
        monkeypatch.setattr(changes.time, "sleep", lambda s: None)
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("503")
        assert summarise_changes(diff_versions(OLD, NEW), "X", "en", client=client) is None
        assert client.models.generate_content.call_count == 3


DOC = """# Terms of Service

Intro paragraph. """ + ("More intro text. " * 20) + """

## 4. Content

### 4.3 Permissions You Give to Us

""" + ("You grant us a worldwide licence to host your content. " * 15) + """

**6. Content Removal**

We can remove content. """ + ("Deletion takes thirty days. " * 25)


class TestChunking:
    def test_chunks_keep_their_section_path(self):
        chunks = chunk_document(DOC, size=400, overlap=60)
        licence = [c for c in chunks if "worldwide licence" in c.content]
        assert licence and all(c.section.endswith("4.3 Permissions You Give to Us") for c in licence)
        assert "Terms of Service > 4. Content" in licence[0].section

    def test_bold_lines_act_as_headings(self):
        chunks = chunk_document(DOC, size=400, overlap=60)
        assert any(c.section.endswith("6. Content Removal") for c in chunks)

    def test_section_is_embedded_but_not_in_content(self):
        c = next(c for c in chunk_document(DOC, size=400, overlap=60) if "licence" in c.content)
        assert c.section in c.embed_text and c.section not in c.content

    def test_inline_headings_in_single_line_documents(self):
        flat = "Preamble text here. ## **5. Rights We Retain** " + "We retain all rights to our content. " * 20
        chunks = chunk_document(flat, size=300, overlap=40)
        assert any("Rights We Retain" in c.section for c in chunks)

    def test_respects_size(self):
        assert all(len(c.content) <= 420 for c in chunk_document(DOC, size=400, overlap=60))

    def test_plain_text_without_headings(self):
        chunks = chunk_document("Sentence number one is here. " * 100, size=300, overlap=40)
        assert len(chunks) > 3 and all(c.section == "" for c in chunks)
