from unittest.mock import AsyncMock, MagicMock

import pytest

import rag


def client_returning(text=None, error=None):
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        side_effect=error, return_value=MagicMock(text=text)
    )
    return client


class TestParseRanking:
    def test_plain_array(self):
        assert rag.parse_ranking("[3, 1, 7]", 10) == [2, 0, 6]

    def test_noise_duplicates_and_out_of_range(self):
        assert rag.parse_ranking("Sure! [2, 2, 99, 0, 1] hope it helps", 5) == [1, 0]

    def test_no_array(self):
        assert rag.parse_ranking("I cannot", 5) == [] and rag.parse_ranking(None, 5) == []


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(rag.asyncio, "sleep", AsyncMock())


@pytest.mark.asyncio
class TestRerank:
    async def test_transient_error_is_retried_once(self):
        client = MagicMock()
        client.aio.models.generate_content = AsyncMock(side_effect=[RuntimeError("503"), MagicMock(text="[2, 1]")])
        assert await rag.rerank(client, "m", "q", ["a", "b", "c"], top_k=3) == [1, 0, 2]
        assert client.aio.models.generate_content.await_count == 2

    async def test_orders_by_model_and_keeps_the_rest(self):
        order = await rag.rerank(client_returning("[3, 1]"), "m", "q", ["a", "b", "c", "d"], top_k=4)
        assert order == [2, 0, 1, 3]

    async def test_truncates_to_top_k(self):
        order = await rag.rerank(client_returning("[4, 3, 2, 1]"), "m", "q", list("abcd"), top_k=2)
        assert order == [3, 2]

    async def test_failure_keeps_retrieval_order(self):
        order = await rag.rerank(client_returning(error=RuntimeError("503")), "m", "q", list("abc"), top_k=2)
        assert order == [0, 1]

    async def test_single_candidate_skips_the_llm(self):
        client = client_returning("[1]")
        assert await rag.rerank(client, "m", "q", ["only"], 5) == [0]
        client.aio.models.generate_content.assert_not_awaited()


@pytest.mark.asyncio
class TestRewrite:
    history = [("user", "Does TikTok collect my location?"), ("model", "Yes, GPS with permission.")]

    async def test_no_history_returns_question_untouched(self):
        client = client_returning("x")
        assert await rag.rewrite_query(client, "m", [], "hello there") == "hello there"
        client.aio.models.generate_content.assert_not_awaited()

    async def test_rewrites_with_history_in_prompt(self):
        client = client_returning('"What keystroke data does TikTok collect?"\nextra line')
        out = await rag.rewrite_query(client, "m", self.history, "And what I type?")
        assert out == "What keystroke data does TikTok collect?"
        prompt = client.aio.models.generate_content.call_args.kwargs["contents"]
        assert "USER: Does TikTok collect my location?" in prompt and "And what I type?" in prompt

    async def test_failure_or_garbage_falls_back(self):
        assert await rag.rewrite_query(client_returning(error=RuntimeError("x")), "m", self.history, "q?") == "q?"
        assert await rag.rewrite_query(client_returning(""), "m", self.history, "q?") == "q?"
