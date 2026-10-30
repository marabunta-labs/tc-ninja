"""Passage embeddings: Gemini in batches, L2-normalised, retrying rate limits."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.genai import errors

import update_terms as ut


def _response(vectors):
    return SimpleNamespace(embeddings=[SimpleNamespace(values=v) for v in vectors])


@pytest.fixture
def fake_gemini(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ut, "get_gemini", lambda: client)
    monkeypatch.setattr(ut.time, "sleep", lambda s: None)
    return client


def test_vectors_are_normalised_and_use_the_document_task(fake_gemini):
    fake_gemini.models.embed_content.return_value = _response([[3.0, 4.0] + [0.0] * 382])
    [vec] = ut.embed_chunks(["hello"])
    assert vec[:2] == [0.6, 0.8] and abs(sum(x * x for x in vec) - 1.0) < 1e-9
    kwargs = fake_gemini.models.embed_content.call_args.kwargs
    assert kwargs["model"] == ut.EMBEDDING["model"] and kwargs["contents"] == ["hello"]
    assert kwargs["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert kwargs["config"].output_dimensionality == ut.EMBEDDING["dimensions"] == 384


def test_texts_are_sent_in_batches_keeping_order(fake_gemini):
    texts = [f"t{i}" for i in range(ut.EMBED_BATCH * 2 + 3)]
    fake_gemini.models.embed_content.side_effect = lambda model, contents, config: _response([[float(c[1:]) + 1.0] for c in contents])
    out = ut.embed_chunks(texts)
    assert [c.kwargs["contents"] for c in fake_gemini.models.embed_content.call_args_list] == [
        texts[:ut.EMBED_BATCH], texts[ut.EMBED_BATCH:2 * ut.EMBED_BATCH], texts[2 * ut.EMBED_BATCH:]]
    assert len(out) == len(texts) and all(v == [1.0] for v in out)  # each [x] normalises to [1.0]


def test_rate_limits_are_retried_then_succeed(fake_gemini):
    limited = errors.APIError(429, {"error": {"message": "quota"}})
    fake_gemini.models.embed_content.side_effect = [limited, limited, _response([[1.0, 0.0]])]
    assert ut.embed_chunks(["a"]) == [[1.0, 0.0]]
    assert fake_gemini.models.embed_content.call_count == 3


def test_non_retryable_errors_fail_immediately(fake_gemini):
    fake_gemini.models.embed_content.side_effect = errors.APIError(403, {"error": {"message": "bad key"}})
    with pytest.raises(errors.APIError):
        ut.embed_chunks(["a"])
    assert fake_gemini.models.embed_content.call_count == 1


def test_gives_up_after_the_retry_budget(fake_gemini):
    fake_gemini.models.embed_content.side_effect = errors.APIError(429, {"error": {"message": "quota"}})
    with pytest.raises(errors.APIError):
        ut.embed_chunks(["a"])
    assert fake_gemini.models.embed_content.call_count == ut.EMBED_RETRIES


def test_mismatched_response_size_is_an_error(fake_gemini):
    fake_gemini.models.embed_content.return_value = _response([[1.0]])
    with pytest.raises(RuntimeError):
        ut.embed_chunks(["a", "b"])


def test_daily_quota_is_not_retried_but_reported(fake_gemini):
    daily = errors.APIError(429, {"error": {"message": "limit", "details": [
        {"violations": [{"quotaId": "EmbedContentRequestsPerDayPerUserPerProjectPerModel-FreeTier"}]}]}})
    fake_gemini.models.embed_content.side_effect = daily
    with pytest.raises(ut.QuotaExhausted):
        ut.embed_chunks(["a"])
    assert fake_gemini.models.embed_content.call_count == 1  # waiting seconds cannot fix a daily limit
