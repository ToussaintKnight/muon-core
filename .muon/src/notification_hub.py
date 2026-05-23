"""Notification Hub — unified message push service.

Design decisions:
- Three levels: critical / normal / info with emoji prefixes
- Async API to match Gateway's async handler pattern
- Message formatting with truncation safety for Telegram's 4096 char limit
- Inline keyboard actions for critical notifications (view logs, resolve, etc.)
- API errors are logged, not raised — notifications should never crash the caller
- Uses aiohttp for async HTTP (already in requirements)
"""

import logging
import aiohttp

logger = logging.getLogger(__name__)
TELEGRAM_MAX_LENGTH = 4096


class NotificationLevel:
    """Notification priority levels."""
    CRITICAL = "critical"
    NORMAL = "normal"
    INFO = "info"


class NotificationHub:
    """Unified message push service for all components.

    Any component (CLI Hook, Gateway, Agent) can call methods on this hub
    to push notifications to the user's phone via Telegram Bot API.
    """

    _LEVEL_EMOJI = {
        NotificationLevel.CRITICAL: "🔴",
        NotificationLevel.NORMAL: "🟢",
        NotificationLevel.INFO: "🔵",
    }

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    @staticmethod
    def _is_valid_level(level: str) -> bool:
        """Check if a level string is valid."""
        return level in {
            NotificationLevel.CRITICAL,
            NotificationLevel.NORMAL,
            NotificationLevel.INFO,
        }

    def _format_message(self, level: str, task_id: str, message: str) -> str:
        """Format a notification message with emoji and truncation safety."""
        emoji = self._LEVEL_EMOJI.get(level, "⚪")
        header = f"{emoji} [{level.upper()}] {task_id}"
        full = f"{header}\n\n{message}"

        if len(full) > TELEGRAM_MAX_LENGTH:
            truncate_notice = f"\n\n... (truncated)"
            max_msg_len = TELEGRAM_MAX_LENGTH - len(header) - len(truncate_notice) - 2
            message = message[:max_msg_len] + truncate_notice
            full = f"{header}\n\n{message}"

        return full

    def _build_keyboard(self, actions: list | None) -> dict | None:
        """Build Telegram inline keyboard from action list.

        actions: [{"text": "View logs", "callback": "/logs task-42"}, ...]
        """
        if not actions:
            return None

        keyboard = []
        for action in actions:
            keyboard.append([{
                "text": action["text"],
                "callback_data": action["callback"]
            }])
        return {"inline_keyboard": keyboard}

    async def _send(self, text: str, reply_markup: dict | None = None):
        """Send a message via Telegram Bot API."""
        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        logger.warning(
                            "Failed to send notification: HTTP %s - %s",
                            response.status,
                            await response.text()
                        )
        except Exception as e:
            logger.exception("Failed to send notification: %s", e)

    async def critical(
        self,
        task_id: str,
        agent: str,
        message: str,
        actions: list = None
    ):
        """Send a critical notification (immediate attention required)."""
        text = self._format_message(
            NotificationLevel.CRITICAL,
            task_id,
            f"Agent: {agent}\n{message}"
        )
        keyboard = self._build_keyboard(actions)
        await self._send(text, reply_markup=keyboard)

    async def normal(self, task_id: str, agent: str, message: str):
        """Send a normal notification (task complete, PR ready, etc.)."""
        text = self._format_message(
            NotificationLevel.NORMAL,
            task_id,
            f"Agent: {agent}\n{message}"
        )
        await self._send(text)

    async def info(self, task_id: str, message: str):
        """Send an info notification (daily summary, heartbeat)."""
        text = self._format_message(NotificationLevel.INFO, task_id, message)
        await self._send(text)
