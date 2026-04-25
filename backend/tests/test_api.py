import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from main import app, detect_platforms, VALID_PLATFORMS, VALID_MODES


client = TestClient(app)


class TestInputValidation:
    def test_ask_rejects_invalid_platforms(self):
        response = client.post("/ask", json={
            "platforms": ["FakePlatform", "HackerNet"],
            "messages": [{"role": "user", "content": "test"}],
            "mode": "explanation",
            "language": "es",
        })
        assert response.status_code == 200
        assert "No valid platforms" in response.text

    def test_ask_sanitizes_mode(self):
        with patch("main.model") as mock_model, \
             patch("main.supabase") as mock_sb, \
             patch("main.genai") as mock_genai:
            mock_model.encode.return_value = MagicMock(tolist=lambda: [0.0] * 384)
            mock_rpc = MagicMock()
            mock_rpc.execute.return_value = MagicMock(data=[])
            mock_sb.rpc.return_value = mock_rpc

            mock_chat = MagicMock()
            mock_chat.send_message_async = AsyncMock(return_value=AsyncMock(
                __aiter__=lambda self: self,
                __anext__=AsyncMock(side_effect=StopAsyncIteration),
            ))
            mock_gemini_model = MagicMock()
            mock_gemini_model.start_chat.return_value = mock_chat
            mock_genai.GenerativeModel.return_value = mock_gemini_model

            response = client.post("/ask", json={
                "platforms": ["Instagram"],
                "messages": [{"role": "user", "content": "test"}],
                "mode": "INJECTED_PROMPT_HERE",
                "language": "es",
            })
            assert response.status_code == 200

    def test_ask_sanitizes_language(self):
        with patch("main.model") as mock_model, \
             patch("main.supabase") as mock_sb, \
             patch("main.genai") as mock_genai:
            mock_model.encode.return_value = MagicMock(tolist=lambda: [0.0] * 384)
            mock_rpc = MagicMock()
            mock_rpc.execute.return_value = MagicMock(data=[])
            mock_sb.rpc.return_value = mock_rpc

            mock_chat = MagicMock()
            mock_chat.send_message_async = AsyncMock(return_value=AsyncMock(
                __aiter__=lambda self: self,
                __anext__=AsyncMock(side_effect=StopAsyncIteration),
            ))
            mock_gemini_model = MagicMock()
            mock_gemini_model.start_chat.return_value = mock_chat
            mock_genai.GenerativeModel.return_value = mock_gemini_model

            response = client.post("/ask", json={
                "platforms": ["TikTok"],
                "messages": [{"role": "user", "content": "hello"}],
                "mode": "explanation",
                "language": "fr",
            })
            assert response.status_code == 200


class TestDetectPlatforms:
    @patch("main.genai")
    def test_returns_valid_platforms_only(self, mock_genai):
        mock_response = MagicMock()
        mock_response.text = "Instagram, FakeNet, TikTok"
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        result = detect_platforms("Tell me about Instagram and TikTok", ["Instagram"])
        assert result == ["Instagram", "TikTok"]

    @patch("main.genai")
    def test_returns_empty_on_garbage(self, mock_genai):
        mock_response = MagicMock()
        mock_response.text = "I don't know what you mean"
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        result = detect_platforms("random text", ["Instagram"])
        assert result == []


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


class TestConstants:
    def test_valid_platforms_set(self):
        assert "Instagram" in VALID_PLATFORMS
        assert "TikTok" in VALID_PLATFORMS
        assert "X-Twitter" in VALID_PLATFORMS
        assert "Facebook" in VALID_PLATFORMS
        assert "YouTube" in VALID_PLATFORMS
        assert "LinkedIn" in VALID_PLATFORMS
        assert "Snapchat" in VALID_PLATFORMS
        assert "WhatsApp" in VALID_PLATFORMS
        assert "Telegram" in VALID_PLATFORMS
        assert "BeReal" in VALID_PLATFORMS
        assert len(VALID_PLATFORMS) == 10

    def test_valid_modes_set(self):
        assert "explanation" in VALID_MODES
        assert "legal" in VALID_MODES
