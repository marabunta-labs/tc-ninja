"""process_platform_lang end-to-end with a fake Supabase (no network, no model)."""
import pytest

import update_terms as ut
from fetchers import Fetched
from scraping import FetchError

OLD_TEXT = "## Retention\n\nWe keep your data for twelve months after you close your account. " * 30
NEW_TEXT = "## Retention\n\nWe keep your data for thirty days after you close your account. " * 30
PLATFORM = {"id": "Telegram", "scrapeUrls": {"en": ["https://r.jina.ai/https://t.org/tos"]}}


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.op, self.payload, self.filters = db, table, "select", None, {}

    def select(self, *a, **k): return self
    def eq(self, k, v): self.filters[k] = v; return self
    def like(self, k, v): return self
    def limit(self, n): return self
    def order(self, *a, **k): return self
    def insert(self, rows): self.op, self.payload = "insert", rows; return self
    def delete(self): self.op = "delete"; return self

    def execute(self):
        db = self.db
        if self.op == "insert" and self.table == "document_versions":
            row = dict(self.payload, id=len(db.versions) + 1); db.versions.append(row)
            return type("R", (), {"data": [row]})
        if self.op == "insert":
            db.chunks.extend(self.payload); return type("R", (), {"data": self.payload})
        if self.op == "delete":
            db.deleted.append((self.table, dict(self.filters))); return type("R", (), {"data": []})
        rows = [v for v in db.versions if all(v.get(k) == x for k, x in self.filters.items())]
        return type("R", (), {"data": rows})


class FakeDb:
    def __init__(self, versions=()):
        self.versions, self.chunks, self.deleted, self.activated = list(versions), [], [], []

    def table(self, name): return Query(self, name)

    def rpc(self, name, params):
        self.activated.append((name, params))
        return type("Q", (), {"execute": lambda self: None})()


@pytest.fixture
def env(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(ut, "get_supabase", lambda: db)
    monkeypatch.setattr(ut, "embed_chunks", lambda texts: [[0.0] * 384 for _ in texts])
    monkeypatch.setattr(ut, "purge_old_versions", lambda *a: None)
    monkeypatch.setattr(ut, "build_changes", lambda *a, **k: {"previous_version": a[2], "added": 1, "removed": 1})
    state = {"text": NEW_TEXT, "language_ok": True}

    def fake_fetch(url, lang, chain):
        if state["text"] is None:
            raise FetchError("blocked")
        return Fetched(state["text"], "jina", state["language_ok"], "en")

    monkeypatch.setattr(ut, "fetch_source_text", fake_fetch)
    return db, state


def test_first_version_is_stored_and_activated(env):
    db, _ = env
    assert ut.process_platform_lang(PLATFORM, "en") == "updated"
    v = db.versions[0]
    assert v["embedding_model"] == ut.EMBEDDING["id"] and v["full_text"].startswith("## Retention")
    assert v["stats"]["chunks"] == len(db.chunks) > 0
    assert db.activated == [("activate_document_version", {"p_version_id": 1})]
    assert all(c["metadata"]["section"] == "Retention" and c["version_id"] == 1 for c in db.chunks)


def test_unchanged_content_does_nothing(env):
    db, _ = env
    db.versions.append({"id": 1, "platform": "Telegram", "language": "en", "status": "current",
                        "version": "2026-01-01", "content_hash": ut.content_hash(NEW_TEXT), "stats": {},
                        "embedding_model": ut.EMBEDDING["id"]})
    assert ut.process_platform_lang(PLATFORM, "en") == "unchanged"
    assert not db.chunks and not db.activated


def test_changed_content_creates_version_with_changes(env):
    db, state = env
    db.versions.append({"id": 1, "platform": "Telegram", "language": "en", "status": "current",
                        "version": "2026-01-01", "content_hash": "old", "full_text": OLD_TEXT, "stats": {}})
    assert ut.process_platform_lang(PLATFORM, "en") == "updated"
    assert db.versions[1]["changes"]["previous_version"] == "2026-01-01"
    assert db.activated[-1][1] == {"p_version_id": 2}


def test_failed_fetch_leaves_data_untouched(env):
    db, state = env
    state["text"] = None
    assert ut.process_platform_lang(PLATFORM, "en") == "failed"
    assert not db.versions and not db.chunks and not db.activated


def test_language_mismatch_is_recorded_not_fatal(env):
    db, state = env
    state["language_ok"] = False
    assert ut.process_platform_lang(PLATFORM, "en") == "updated"
    assert db.versions[0]["stats"]["language_mismatch"] == ["https://t.org/tos"]


def test_insert_failure_rolls_back_pending_version(env, monkeypatch):
    db, _ = env
    original = Query.execute

    def boom(self):
        if self.op == "insert" and self.table == "documents":
            raise RuntimeError("db down")
        return original(self)

    monkeypatch.setattr(Query, "execute", boom)
    assert ut.process_platform_lang(PLATFORM, "en") == "failed"
    assert ("document_versions", {"id": 1}) in db.deleted and not db.activated


def test_same_text_but_other_embedding_model_is_re_embedded(env):
    db, _ = env
    db.versions.append({"id": 1, "platform": "Telegram", "language": "en", "status": "current",
                        "version": "2026-01-01", "content_hash": ut.content_hash(NEW_TEXT), "full_text": NEW_TEXT,
                        "stats": {}, "embedding_model": "multilingual-e5-small"})
    assert ut.process_platform_lang(PLATFORM, "en") == "updated"
    assert db.versions[1]["embedding_model"] == ut.EMBEDDING["id"] and db.chunks
    assert db.activated[-1][1] == {"p_version_id": 2}


def test_unknown_embedding_model_counts_as_stale(env):
    db, _ = env
    db.versions.append({"id": 1, "platform": "Telegram", "language": "en", "status": "current",
                        "version": "2026-01-01", "content_hash": ut.content_hash(NEW_TEXT), "stats": {}})  # no embedding_model
    assert ut.process_platform_lang(PLATFORM, "en") == "updated"


def test_daily_quota_stops_the_run_cleanly_and_keeps_the_data(env, monkeypatch, capsys):
    db, _ = env
    db.versions.append({"id": 1, "platform": "Telegram", "language": "en", "status": "current",
                        "version": "2026-01-01", "content_hash": "old", "full_text": OLD_TEXT, "stats": {},
                        "embedding_model": ut.EMBEDDING["id"]})

    def quota(texts):
        raise ut.QuotaExhausted("EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier")

    monkeypatch.setattr(ut, "embed_chunks", quota)
    monkeypatch.setattr(ut, "PLATFORMS", [PLATFORM, {"id": "Other", "scrapeUrls": {"en": ["https://o.org"], "es": ["https://o.org/es"]}}])
    assert ut.main([]) == 0  # deferred is not a failure: the run stays green and resumes next time
    out = capsys.readouterr().out
    assert "quota exhausted" in out and "3 deferred" in out
    assert len(db.versions) == 1 and not db.chunks and not db.activated  # nothing written
