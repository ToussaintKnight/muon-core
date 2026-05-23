"""
Test Driven Development for Telegram Gateway.

Tests cover:
- Message handler routes commands to CommandProxy
- Reply is sent back to Telegram chat
- /start command returns welcome message
- Error handling in message handler
- Long message truncation before sending
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
import asyncio
from src.gateway import TelegramGateway


@pytest.fixture
def mock_proxy():
    proxy = Mock()
    proxy.handle = AsyncMock(return_value="Mocked response")
    return proxy


@pytest.fixture
def mock_bot():
    bot = Mock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def gateway(mock_proxy, mock_bot):
    return TelegramGateway(
        bot_token="fake_token",
        proxy=mock_proxy,
        bot=mock_bot
    )


def make_update(text: str, chat_id: int = 12345) -> Mock:
    """Create a mock Telegram Update object."""
    update = Mock()
    update.message = Mock()
    update.message.text = text
    update.effective_chat = Mock()
    update.effective_chat.id = chat_id
    return update


def make_context(bot) -> Mock:
    """Create a mock Telegram Context object."""
    context = Mock()
    context.bot = bot
    return context


class TestMessageHandler:
    """Tests for the main message/command handler."""

    @pytest.mark.asyncio
    async def test_command_routed_to_proxy(self, gateway, mock_proxy, mock_bot):
        update = make_update("/status")
        context = make_context(mock_bot)
        await gateway._handle_message(update, context)
        mock_proxy.handle.assert_awaited_once_with("/status")

    @pytest.mark.asyncio
    async def test_reply_sent_to_chat(self, gateway, mock_proxy, mock_bot):
        mock_proxy.handle.return_value = "Task list here"
        update = make_update("/status")
        context = make_context(mock_bot)
        await gateway._handle_message(update, context)
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=12345, text="Task list here"
        )

    @pytest.mark.asyncio
    async def test_empty_message_ignored(self, gateway, mock_proxy, mock_bot):
        update = make_update("")
        context = make_context(mock_bot)
        await gateway._handle_message(update, context)
        mock_proxy.handle.assert_not_called()
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_plain_text_treated_as_ask(self, gateway, mock_proxy, mock_bot):
        update = make_update("how do I fix this bug")
        context = make_context(mock_bot)
        await gateway._handle_message(update, context)
        mock_proxy.handle.assert_awaited_once_with("/ask how do I fix this bug")


class TestStartCommand:
    """Tests for /start handler."""

    @pytest.mark.asyncio
    async def test_start_returns_welcome(self, gateway, mock_bot):
        update = make_update("/start")
        context = make_context(mock_bot)
        await gateway._handle_start(update, context)
        mock_bot.send_message.assert_awaited_once()
        sent_text = mock_bot.send_message.call_args[1]["text"]
        assert "muon" in sent_text.lower() or "ooo" in sent_text.lower()
        assert "/status" in sent_text


class TestLongMessageHandling:
    """Tests for Telegram message length limits."""

    @pytest.mark.asyncio
    async def test_long_reply_truncated(self, gateway, mock_proxy, mock_bot):
        long_response = "x" * 5000
        mock_proxy.handle.return_value = long_response
        update = make_update("/status")
        context = make_context(mock_bot)
        await gateway._handle_message(update, context)
        sent_text = mock_bot.send_message.call_args[1]["text"]
        assert len(sent_text) <= 4096

    @pytest.mark.asyncio
    async def test_short_reply_not_truncated(self, gateway, mock_proxy, mock_bot):
        mock_proxy.handle.return_value = "short"
        update = make_update("/status")
        context = make_context(mock_bot)
        await gateway._handle_message(update, context)
        sent_text = mock_bot.send_message.call_args[1]["text"]
        assert sent_text == "short"


class TestErrorHandling:
    """Tests for graceful error handling in gateway."""

    @pytest.mark.asyncio
    async def test_proxy_error_sends_error_message(self, gateway, mock_proxy, mock_bot):
        mock_proxy.handle.side_effect = Exception("proxy crashed")
        update = make_update("/status")
        context = make_context(mock_bot)
        await gateway._handle_message(update, context)
        mock_bot.send_message.assert_awaited_once()
        sent_text = mock_bot.send_message.call_args[1]["text"]
        assert "error" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_send_failure_logged(self, gateway, mock_proxy, mock_bot):
        mock_proxy.handle.return_value = "ok"
        mock_bot.send_message.side_effect = Exception("network down")
        update = make_update("/status")
        context = make_context(mock_bot)
        # Should not raise
        await gateway._handle_message(update, context)


class TestGatewayLifecycle:
    """Tests for bot startup and shutdown."""

    def test_initialization_stores_token(self, mock_proxy):
        gw = TelegramGateway(bot_token="test123", proxy=mock_proxy)
        assert gw.bot_token == "test123"

    def test_initialization_stores_proxy(self, mock_proxy):
        gw = TelegramGateway(bot_token="test123", proxy=mock_proxy)
        assert gw.proxy is mock_proxy
