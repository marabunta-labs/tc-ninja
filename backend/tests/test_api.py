import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

import main
from main import (
    app,
    detect_platforms,
    is_comparison_query,
    retrieve_context,
    text_fragment_link,
    VALID_PLATFORMS,
    VALID_MODES,
)


client = TestClient(app)


class FakeStream:
    """Async iterable mimicking a Gemini streaming response."""

    def __init__(self, *texts):
        self._chunks = [MagicMock(text=t) for t in texts]

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


def _chunk(content, version="2026-09-01", status="current", url="https://example.com/tos"):
    return {
        "content": content,
        "metadata": {"source_url": url, "fetch_date": version},
        "version": version,
        "version_status": status,
    }


@pytest.fixture
def ask_mocks():
    """Patch every external service used by /ask and expose the Gemini model mock.

    Rerank and query rewriting are off here; tests that cover them switch them on.
    """
    with patch("main.embed", new=AsyncMock(return_value=[0.0] * 384)) as mock_embed, \
         patch("main.supabase") as mock_sb, \
         patch("main.gemini") as mock_gemini, \
         patch("main.RAG_RERANK", False), \
         patch("main.RAG_REWRITE", False):
        mock_sb.rpc.return_value.execute.return_value = MagicMock(data=[_chunk("We store your data.")])
        chat = MagicMock()
        chat.send_message_stream = AsyncMock(return_value=FakeStream("Hello ", "ninja"))
        mock_gemini.aio.chats.create.return_value = chat
        yield MagicMock(sb=mock_sb, gemini=mock_gemini, chat=chat, embed=mock_embed)


class TestInputValidation:
    def test_ask_rejects_invalid_platforms(self):
        response = client.post("/ask", json={
            "platforms": ["FakePlatform", "HackerNet"],
            "messages": [{"role": "user", "content": "test"}],
        })
        assert response.status_code == 200
        assert "No valid platforms" in response.text

    def test_ask_rejects_empty_messages(self):
        response = client.post("/ask", json={"platforms": ["Instagram"], "messages": []})
        assert response.status_code == 422

    def test_ask_rejects_oversized_message(self):
        response = client.post("/ask", json={
            "platforms": ["Instagram"],
            "messages": [{"role": "user", "content": "x" * 5_000}],
        })
        assert response.status_code == 422

    def test_ask_sanitizes_mode_and_language(self, ask_mocks):
        response = client.post("/ask", json={
            "platforms": ["Instagram"],
            "messages": [{"role": "user", "content": "test"}],
            "mode": "INJECTED_PROMPT_HERE",
            "language": "fr",
        })
        assert response.status_code == 200
        assert response.text == "Hello ninja"

    def test_history_never_starts_with_model_turn(self, ask_mocks):
        messages = [{"role": "model", "content": "old answer"}] + [
            {"role": "user", "content": "q"}
        ]
        client.post("/ask", json={"platforms": ["Instagram"], "messages": messages})
        history = ask_mocks.gemini.aio.chats.create.call_args.kwargs["history"]
        assert history == []


class TestEmbedding:
    """Queries are embedded with Gemini; if that fails the chat keeps working with full-text search."""

    @staticmethod
    def _response(values):
        return MagicMock(embeddings=[MagicMock(values=values)])

    def test_query_vector_is_normalised_and_uses_the_query_task(self):
        with patch("main.gemini") as g:
            g.aio.models.embed_content = AsyncMock(return_value=self._response([3.0, 4.0] + [0.0] * 382))
            vec = asyncio.run(main.embed("hello"))
        assert abs(sum(x * x for x in vec) - 1.0) < 1e-9 and vec[:2] == [0.6, 0.8]
        kwargs = g.aio.models.embed_content.call_args.kwargs
        assert kwargs["model"] == main.EMBEDDING["model"] and kwargs["contents"] == ["hello"]
        assert kwargs["config"].task_type == "RETRIEVAL_QUERY"
        assert kwargs["config"].output_dimensionality == main.EMBEDDING["dimensions"] == 384

    def test_rate_limit_is_retried(self):
        limited = main.genai_errors.APIError(429, {"error": {"message": "quota"}})
        with patch("main.gemini") as g, patch("main.asyncio.sleep", new=AsyncMock()):
            g.aio.models.embed_content = AsyncMock(side_effect=[limited, self._response([1.0] + [0.0] * 383)])
            vec = asyncio.run(main.embed("hello"))
        assert vec[0] == 1.0 and g.aio.models.embed_content.await_count == 2

    def test_other_errors_are_not_retried(self):
        denied = main.genai_errors.APIError(403, {"error": {"message": "key"}})
        with patch("main.gemini") as g:
            g.aio.models.embed_content = AsyncMock(side_effect=denied)
            with pytest.raises(main.genai_errors.APIError):
                asyncio.run(main.embed("hello"))
        assert g.aio.models.embed_content.await_count == 1

    def test_chat_survives_embedding_outage_with_text_only_search(self, ask_mocks):
        ask_mocks.embed.side_effect = RuntimeError("402 Payment Required")
        r = client.post("/ask", json={
            "platforms": ["Instagram"],
            "messages": [{"role": "user", "content": "What data do you keep?"}],
            "language": "en",
        })
        assert r.status_code == 200 and "Ninja out of service" not in r.text
        name, params = ask_mocks.sb.rpc.call_args.args
        assert name == "match_documents_hybrid" and params["query_embedding"] is None
        assert params["query_text"] == "What data do you keep?"

    def test_plain_vector_search_is_skipped_without_a_vector(self):
        with patch("main.supabase") as sb:
            sb.rpc.return_value.execute.side_effect = Exception("function match_documents_hybrid does not exist")
            assert main.search_chunks(None, "keep data", "Instagram", "en", 5) == []
        assert [c.args[0] for c in sb.rpc.call_args_list] == ["match_documents_hybrid"]


class TestRetrieval:
    def test_regular_question_searches_current_version_only(self, ask_mocks):
        client.post("/ask", json={
            "platforms": ["Instagram"],
            "messages": [{"role": "user", "content": "What data do you keep?"}],
            "language": "en",
        })
        name, params = ask_mocks.sb.rpc.call_args.args
        assert name == "match_documents_hybrid"
        assert "filter_version" not in params  # SQL default NULL → current only
        assert params["query_text"] == "What data do you keep?"
        assert params["filter_embedding_model"] == main.EMBEDDING["id"]

    def test_falls_back_to_vector_search_without_migration(self, ask_mocks):
        def rpc(name, params):
            if name == "match_documents_hybrid":
                raise RuntimeError("function does not exist")
            return MagicMock(execute=lambda: MagicMock(data=[_chunk("vector only")]))

        ask_mocks.sb.rpc.side_effect = rpc
        result = retrieve_context("Instagram", [0.0], "q", "en", comparison=False)
        assert result["chunks"][0]["content"] == "vector only"

    def test_current_chunks_are_tagged_current(self, ask_mocks):
        client.post("/ask", json={
            "platforms": ["Instagram"],
            "messages": [{"role": "user", "content": "What data do you keep?"}],
        })
        prompt = ask_mocks.chat.send_message_stream.call_args.args[0]
        assert "Status: CURRENT" in prompt and "Version: 2026-09-01" in prompt

    def test_section_is_shown_to_the_model(self, ask_mocks):
        doc = _chunk("Deletion takes 30 days.")
        doc["metadata"]["section"] = "Content Removal"
        ask_mocks.sb.rpc.return_value.execute.return_value = MagicMock(data=[doc])
        client.post("/ask", json={"platforms": ["Instagram"], "messages": [{"role": "user", "content": "deletion?"}]})
        assert "Section: Content Removal" in ask_mocks.chat.send_message_stream.call_args.args[0]

    def test_comparison_tags_deprecated_version(self):
        versions = [
            {"version": "2026-09-01", "status": "current"},
            {"version": "2026-03-01", "status": "superseded"},
        ]
        with patch("main.list_versions", return_value=versions), \
             patch("main.search_chunks") as search:
            search.side_effect = [
                [_chunk("new clause", "2026-09-01", "current")],
                [_chunk("old clause", "2026-03-01", "superseded")],
            ]
            result = retrieve_context("Instagram", [0.0], "q", "en", comparison=True)
        assert [(c["version"], c["status"]) for c in result["chunks"]] == [
            ("2026-09-01", "current"),
            ("2026-03-01", "superseded"),
        ]
        assert [c.kwargs["version"] for c in search.call_args_list] == ["2026-09-01", "2026-03-01"]

    def test_language_fallback(self):
        with patch("main.search_chunks", side_effect=[[], [_chunk("English only")]]):
            result = retrieve_context("Instagram", [0.0], "q", "es", comparison=False)
        assert result["chunks"][0]["content"] == "English only"

    def test_comparison_prompt_marks_superseded_and_includes_changelog(self, ask_mocks):
        versions = [
            {"version": "2026-09-01", "status": "current",
             "changes": {"previous_version": "2026-03-01", "summary": "- Retention cut to 30 days"}},
            {"version": "2026-03-01", "status": "superseded"},
        ]
        with patch("main.list_versions", return_value=versions), \
             patch("main.search_chunks", side_effect=[
                 [_chunk("new", "2026-09-01", "current")],
                 [_chunk("old", "2026-03-01", "superseded")],
             ]):
            client.post("/ask", json={
                "platforms": ["Instagram"],
                "messages": [{"role": "user", "content": "What changed in the terms?"}],
            })
        prompt = ask_mocks.chat.send_message_stream.call_args.args[0]
        assert "SUPERSEDED — deprecated" in prompt
        assert "AUTOMATIC CHANGELOG — version 2026-09-01 vs 2026-03-01" in prompt
        assert "Retention cut to 30 days" in prompt

    def test_versions_with_another_embedding_model_are_skipped_for_comparison(self):
        rows = [
            {"version": "v3", "status": "current", "embedding_model": main.EMBEDDING["id"]},
            {"version": "v2", "status": "superseded", "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2"},
            {"version": "v1", "status": "superseded", "embedding_model": main.EMBEDDING["id"]},
        ]
        with patch("main.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
                .in_.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=rows)
            assert [v["version"] for v in main.list_versions("Instagram", "en")] == ["v3", "v1"]


class TestQueryPipeline:
    def test_followup_is_rewritten_before_embedding(self, ask_mocks):
        with patch("main.RAG_REWRITE", True), \
             patch("main.rag.rewrite_query", new=AsyncMock(return_value="How long does TikTok keep metadata?")) as rw:
            client.post("/ask", json={
                "platforms": ["TikTok"],
                "messages": [
                    {"role": "user", "content": "What metadata does TikTok collect?"},
                    {"role": "model", "content": "Device and IP data."},
                    {"role": "user", "content": "And how long do they keep it?"},
                ],
            })
        assert rw.call_args.args[2] == [("user", "What metadata does TikTok collect?"), ("model", "Device and IP data.")]
        ask_mocks.embed.assert_awaited_with("How long does TikTok keep metadata?")
        assert ask_mocks.sb.rpc.call_args.args[1]["query_text"] == "How long does TikTok keep metadata?"

    def test_first_message_is_not_rewritten(self, ask_mocks):
        with patch("main.RAG_REWRITE", True), patch("main.rag.rewrite_query", new=AsyncMock()) as rw:
            client.post("/ask", json={"platforms": ["TikTok"], "messages": [{"role": "user", "content": "hi"}]})
        rw.assert_not_awaited()

    def test_rerank_picks_final_chunks_in_order(self, ask_mocks):
        docs = [_chunk(f"chunk {i}") for i in range(12)]
        ask_mocks.sb.rpc.return_value.execute.return_value = MagicMock(data=docs)
        with patch("main.RAG_RERANK", True), \
             patch("main.rag.rerank", new=AsyncMock(return_value=[5, 2, 9])) as rr:
            client.post("/ask", json={"platforms": ["TikTok"], "messages": [{"role": "user", "content": "q"}]})
        assert ask_mocks.sb.rpc.call_args.args[1]["match_count"] == main.RERANK_POOL
        prompt = ask_mocks.chat.send_message_stream.call_args.args[0]
        assert prompt.index("chunk 5") < prompt.index("chunk 2") < prompt.index("chunk 9")
        assert "chunk 0\n" not in prompt

    def test_without_rerank_takes_top_chunks_as_retrieved(self, ask_mocks):
        docs = [_chunk(f"chunk {i}") for i in range(12)]
        ask_mocks.sb.rpc.return_value.execute.return_value = MagicMock(data=docs)
        client.post("/ask", json={"platforms": ["TikTok"], "messages": [{"role": "user", "content": "q"}]})
        assert ask_mocks.sb.rpc.call_args.args[1]["match_count"] == main.FINAL_CHUNKS

    def test_gemini_send_is_retried(self, ask_mocks):
        ask_mocks.chat.send_message_stream = AsyncMock(side_effect=[RuntimeError("503"), FakeStream("ok")])
        with patch("main.asyncio.sleep", new=AsyncMock()):
            response = client.post("/ask", json={"platforms": ["TikTok"], "messages": [{"role": "user", "content": "q"}]})
        assert response.text == "ok"


class TestComparisonDetection:
    @pytest.mark.parametrize("text", [
        "What changed in TikTok's terms?", "¿Qué ha cambiado?", "Compara antes y ahora",
        "show me the previous version", "historial de cambios", "Cambió algo?",
    ])
    def test_positive(self, text):
        assert is_comparison_query(text)

    @pytest.mark.parametrize("text", [
        "Do they sell my constantes vitales?", "Can they delete my account?", "¿Comparten mis datos?",
        "Who can see my photos?",
    ])
    def test_negative(self, text):
        assert not is_comparison_query(text)


class TestTextFragment:
    def test_strips_markdown_and_encodes_hyphen(self):
        link = text_fragment_link("https://a.com/tos", "**You grant** a non-exclusive license, worldwide")
        assert link.startswith("https://a.com/tos#:~:text=You%20grant%20a%20non%2Dexclusive")
        assert "%2A" not in link

    def test_existing_fragment_kept(self):
        assert text_fragment_link("https://a.com/tos#sec", "text") == "https://a.com/tos#sec"

    def test_empty_content(self):
        assert text_fragment_link("https://a.com/tos", "** ") == "https://a.com/tos"


class TestDetectPlatforms:
    @pytest.mark.asyncio
    @patch("main.gemini")
    async def test_returns_valid_platforms_only(self, mock_gemini):
        mock_gemini.aio.models.generate_content = AsyncMock(
            return_value=MagicMock(text="Instagram, FakeNet, TikTok")
        )
        assert await detect_platforms("Instagram and TikTok", ["Instagram"]) == ["Instagram", "TikTok"]

    @pytest.mark.asyncio
    @patch("main.gemini")
    async def test_returns_empty_on_garbage(self, mock_gemini):
        mock_gemini.aio.models.generate_content = AsyncMock(
            return_value=MagicMock(text="I don't know what you mean")
        )
        assert await detect_platforms("random text", ["Instagram"]) == []

    @pytest.mark.asyncio
    @patch("main.gemini")
    async def test_classifier_failure_keeps_context(self, mock_gemini):
        mock_gemini.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("quota")
        )
        assert await detect_platforms("hi", ["Instagram"]) == []


class TestDetectContextEndpoint:
    @patch("main.detect_platforms")
    def test_detect_context_adds_platform(self, mock_detect):
        mock_detect.return_value = ["Instagram", "TikTok"]
        response = client.post("/detect-context", json={
            "message": "Compare Instagram and TikTok",
            "current_platforms": ["Instagram"],
        })
        data = response.json()
        assert response.status_code == 200
        assert "TikTok" in data["platforms"]
        assert data["message"] is not None

    @patch("main.detect_platforms")
    def test_detect_context_no_change(self, mock_detect):
        mock_detect.return_value = ["Instagram"]
        response = client.post("/detect-context", json={
            "message": "Tell me about privacy",
            "current_platforms": ["Instagram"],
        })
        data = response.json()
        assert data["platforms"] == ["Instagram"]
        assert data["message"] is None


class TestVersionsEndpoint:
    def test_lists_current_versions(self):
        rows = [{"platform": "Instagram", "language": "en", "version": "2026-09-01"}]
        with patch("main.supabase") as sb:
            sb.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=rows)
            response = client.get("/versions")
        assert response.json() == {"versions": rows}


class TestConstants:
    def test_valid_platforms_set(self):
        for p in ["Instagram", "TikTok", "X-Twitter", "Facebook", "YouTube",
                  "LinkedIn", "Snapchat", "WhatsApp", "Telegram", "BeReal"]:
            assert p in VALID_PLATFORMS
        assert len(VALID_PLATFORMS) == 10

    def test_valid_modes_set(self):
        assert "explanation" in VALID_MODES
        assert "legal" in VALID_MODES
