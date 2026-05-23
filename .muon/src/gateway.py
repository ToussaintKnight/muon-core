"""Telegram Gateway - Bot entry point that routes messages to Command Proxy.

Design decisions:
- Accepts an optional 'bot' parameter for testing (dependency injection)
- Plain text messages are auto-prefixed with /ask for convenience
- Empty messages are silently ignored
- All errors are caught and sent back as error messages to the user
- Double-truncation: CommandProxy truncates to 4096, Gateway ensures send doesn't exceed
"""

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from src.command_proxy import CommandProxy

logger = logging.getLogger(__name__)
TELEGRAM_MAX_LENGTH = 4096


class TelegramGateway:
    """Telegram Bot gateway that receives messages and delegates to CommandProxy."""

    def __init__(
        self,
        bot_token: str,
        proxy: CommandProxy,
        bot=None
    ):
        self.bot_token = bot_token
        self.proxy = proxy
        self._bot = bot  # Injected for testing; None in production

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        welcome = (
            "Welcome to muon-core OOO Gateway.\n\n"
            "Available commands:\n"
            "  /status - show all tasks\n"
            "  /switch [task] - switch to a task\n"
            "  /ask <question> - ask about current task\n"
            "  /browser <url> - open URL on desktop\n"
            "  /screenshot - capture screen\n\n"
            "Or just type your question and I'll route it to the active agent."
        )
        await self._send_reply(update, context, welcome)

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming text messages (commands and plain text)."""
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()
        if not text:
            return

        # Auto-prefix plain text with /ask for convenience
        if not text.startswith("/"):
            text = f"/ask {text}"

        try:
            response = await self.proxy.handle(text)
        except Exception as e:
            logger.exception("Error handling command")
            response = f"Error processing command: {str(e)}"

        await self._send_reply(update, context, response)

    async def _send_reply(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
        """Send a reply, with truncation safety."""
        chat_id = update.effective_chat.id if update.effective_chat else None
        if not chat_id:
            logger.warning("No chat_id available for reply")
            return

        # Final safety truncation
        if len(text) > TELEGRAM_MAX_LENGTH:
            truncation = f"\n\n... ({len(text) - TELEGRAM_MAX_LENGTH + 50} chars truncated)"
            text = text[:TELEGRAM_MAX_LENGTH - len(truncation)] + truncation

        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.exception("Failed to send reply to chat %s", chat_id)

    def run(self):
        """Start the bot with polling."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        application = Application.builder().token(self.bot_token).build()

        application.add_handler(CommandHandler("start", self._handle_start))
        # Capture ALL text messages including /commands — CommandProxy handles routing
        application.add_handler(
            MessageHandler(filters.TEXT, self._handle_message)
        )

        logger.info("Starting Telegram Gateway...")
        application.run_polling()


if __name__ == "__main__":
    import os
    import yaml
    from src.context_registry import ContextRegistry
    from src.task_switcher import TaskSwitcher

    # Load config from ~/.muon/config.yaml
    config_path = os.path.expanduser("~/.muon/config.yaml")
    if not os.path.exists(config_path):
        print(f"Config not found: {config_path}")
        print("Create it with your bot_token and user_chat_id.")
        exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    token = config.get("telegram", {}).get("bot_token")
    if not token:
        print("bot_token not found in config.yaml")
        exit(1)

    # Initialize core components
    db_path = os.path.expanduser("~/.muon/context.db")
    registry = ContextRegistry(db_path=db_path)
    switcher = TaskSwitcher(context_registry=registry, base_dir=os.path.expanduser("~/projects"))
    proxy = CommandProxy(task_switcher=switcher, context_registry=registry)

    # Start gateway
    gateway = TelegramGateway(bot_token=token, proxy=proxy)
    gateway.run()
