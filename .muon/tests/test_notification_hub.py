"""Tests for Notification Hub — unified message push service.

Design decisions tested:
- Three levels: critical / normal / info
- Async API (matches Gateway async handler)
- Message formatting with emoji + task_id
- Inline keyboard actions for critical notifications
- Mock Telegram HTTP API (no real network calls in tests)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json

from src.notification_hub import NotificationHub, NotificationLevel


class TestNotificationLevel:
    """Tests for level enum and validation."""

    def test_has_three_levels(self):
        assert NotificationLevel.CRITICAL == "critical"
        assert NotificationLevel.NORMAL == "normal"
        assert NotificationLevel.INFO == "info"

    def test_all_levels_valid(self):
        assert NotificationHub._is_valid_level("critical")
        assert NotificationHub._is_valid_level("normal")
        assert NotificationHub._is_valid_level("info")

    def test_invalid_level_rejected(self):
        assert not NotificationHub._is_valid_level("debug")
        assert not NotificationHub._is_valid_level("")
        assert not NotificationHub._is_valid_level(None)


class TestMessageFormatting:
    """Tests for message formatting with emoji and structure."""

    @pytest.fixture
    def hub(self):
        return NotificationHub(bot_token="test_token", chat_id="12345")

    def test_critical_format(self, hub):
        text = hub._format_message(NotificationLevel.CRITICAL, "muon-42", "Test failed")
        assert "🔴" in text
        assert "CRITICAL" in text
        assert "muon-42" in text
        assert "Test failed" in text

    def test_normal_format(self, hub):
        text = hub._format_message(NotificationLevel.NORMAL, "muon-42", "Task done")
        assert "🟢" in text
        assert "NORMAL" in text

    def test_info_format(self, hub):
        text = hub._format_message(NotificationLevel.INFO, "muon-42", "Daily summary")
        assert "🔵" in text
        assert "INFO" in text

    def test_format_truncates_long_message(self, hub):
        long_msg = "x" * 5000
        text = hub._format_message(NotificationLevel.NORMAL, "t", long_msg)
        assert len(text) <= 4096


class TestActionsKeyboard:
    """Tests for inline keyboard actions in critical notifications."""

    @pytest.fixture
    def hub(self):
        return NotificationHub(bot_token="test_token", chat_id="12345")

    def test_build_keyboard(self, hub):
        actions = [
            {"text": "View logs", "callback": "/logs muon-42"},
            {"text": "Resolve", "callback": "/resolve muon-42"}
        ]
        keyboard = hub._build_keyboard(actions)
        assert keyboard["inline_keyboard"][0][0]["text"] == "View logs"
        assert keyboard["inline_keyboard"][0][0]["callback_data"] == "/logs muon-42"
        assert keyboard["inline_keyboard"][1][0]["text"] == "Resolve"

    def test_empty_actions_returns_none(self, hub):
        assert hub._build_keyboard(None) is None
        assert hub._build_keyboard([]) is None


class TestAsyncSend:
    """Tests for async Telegram API calls."""

    @pytest.fixture
    def hub(self):
        return NotificationHub(bot_token="test_token", chat_id="12345")

    @pytest.mark.asyncio
    async def test_critical_sends_post_request(self, hub):
        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_post.return_value.__aenter__.return_value = mock_response

            await hub.critical("muon-42", "hermes", "Build failed")

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "test_token" in str(call_args)
            assert "12345" in str(call_args)

    @pytest.mark.asyncio
    async def test_normal_sends_post_request(self, hub):
        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_post.return_value.__aenter__.return_value = mock_response

            await hub.normal("muon-42", "hermes", "Task completed")

            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_info_sends_post_request(self, hub):
        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_post.return_value.__aenter__.return_value = mock_response

            await hub.info("muon-42", "Daily summary: 2 tasks done")

            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_critical_with_actions_includes_keyboard(self, hub):
        actions = [{"text": "View logs", "callback": "/logs muon-42"}]

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_post.return_value.__aenter__.return_value = mock_response

            await hub.critical("muon-42", "hermes", "Build failed", actions=actions)

            call_kwargs = mock_post.call_args[1]
            payload = call_kwargs.get("json", {})
            assert "reply_markup" in payload
            assert payload["reply_markup"]["inline_keyboard"][0][0]["text"] == "View logs"

    @pytest.mark.asyncio
    async def test_api_error_logged_not_raised(self, hub, caplog):
        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status = 403
            mock_post.return_value.__aenter__.return_value = mock_response

            await hub.critical("muon-42", "hermes", "Build failed")

            assert "Failed to send" in caplog.text or "403" in caplog.text


class TestIntegration:
    """Integration-style tests with real payload inspection."""

    @pytest.fixture
    def hub(self):
        return NotificationHub(bot_token="test_token", chat_id="12345")

    @pytest.mark.asyncio
    async def test_payload_structure(self, hub):
        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_response = MagicMock()
            mock_response.status = 200
            mock_post.return_value.__aenter__.return_value = mock_response

            await hub.critical("task-x", "kimicode", "Oops")

            call_args = mock_post.call_args
            url = call_args[0][0]
            payload = call_args[1]["json"]

            assert "api.telegram.org" in url
            assert "bottest_token" in url
            assert payload["chat_id"] == "12345"
            assert "task-x" in payload["text"]
            assert "Oops" in payload["text"]
