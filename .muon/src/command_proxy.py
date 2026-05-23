"""Command Proxy - Routes Telegram /commands to appropriate handlers.

Design fixes from blueprint v1.0:
- Added _parse() for clean command parsing
- Added _format_output() for Telegram 4096 char limit
- Added graceful error handling with try/except in handle()
- Made handle() async for future extensibility
- Unknown commands return helpful message with available commands
"""

from src.task_switcher import TaskSwitcher
from src.context_registry import ContextRegistry

TELEGRAM_MAX_LENGTH = 4096


class CommandProxy:
    """Routes incoming commands to task operations, context queries, and desktop control."""

    def __init__(
        self,
        task_switcher: TaskSwitcher,
        context_registry: ContextRegistry,
        desktop_api=None
    ):
        self.task_switcher = task_switcher
        self.context_registry = context_registry
        self.desktop_api = desktop_api

    def _parse(self, command: str) -> tuple[str, list[str]]:
        """Parse a command string into command name and arguments."""
        parts = command.strip().split()
        if not parts:
            return "", []
        cmd = parts[0].lstrip("/").lower()
        args = parts[1:]
        return cmd, args

    async def handle(self, command: str) -> str:
        """Route a command to its handler and return the response."""
        cmd, args = self._parse(command)

        if not cmd:
            return "Please enter a command. Type /status to see available tasks."

        handlers = {
            "switch": self._handle_switch,
            "status": self._handle_status,
            "ask": self._handle_ask,
            "browser": self._handle_browser,
            "screenshot": self._handle_screenshot,
            "commit": self._handle_commit,
            "test": self._handle_test,
        }

        handler = handlers.get(cmd)
        if not handler:
            return await self._handle_unknown(cmd)

        try:
            result = await handler(args)
            return await self._format_output(result)
        except Exception as e:
            return f"Error: {str(e)}"

    async def _handle_switch(self, args: list[str]) -> str:
        """Handle /switch [task_id_or_project]."""
        if not args:
            tasks = self.task_switcher.list_tasks()
            if not tasks:
                return "No tasks registered."
            lines = ["Available tasks:"]
            for i, t in enumerate(tasks, 1):
                lines.append(
                    f"{i}. {t['task_id']} ({t['project']}, {t['assigned_agent']}, {t['status']})"
                )
            return "\n".join(lines)

        target = args[0]
        result = self.task_switcher.switch(target)
        return (
            f"Switched to {result['project']}/{result['branch']}\n"
            f"Agent: {result['agent']}\n"
            f"Git: {result['git_status'] or 'clean'}"
        )

    async def _handle_status(self, args: list[str]) -> str:
        """Handle /status - show all tasks."""
        tasks = self.task_switcher.list_tasks()
        if not tasks:
            return "No tasks registered."

        active = self.task_switcher.get_active_task()
        lines = ["Task status:"]
        for t in tasks:
            marker = "->" if t["task_id"] == active else "  "
            lines.append(
                f"{marker} {t['task_id']}: {t['project']} ({t['assigned_agent']}, {t['status']})"
            )
        return "\n".join(lines)

    async def _handle_ask(self, args: list[str]) -> str:
        """Handle /ask <question> - query current task context."""
        if not args:
            return "Usage: /ask <your question>"

        task_id = self.task_switcher.get_active_task()
        if not task_id:
            return "No active task. Use /switch <task> first."

        context = self.context_registry.get_context(task_id, tier=2)
        if not context:
            return f"No context found for active task {task_id}."

        question = " ".join(args)
        # In Phase 0, return context + question for manual forwarding to agent
        # In future phases, this will call the actual agent adapter
        return (
            f"Question: {question}\n\n"
            f"Context ({task_id}):\n"
            f"Summary: {context['summary']}\n"
            f"Detail: {context['detail'] or 'N/A'}\n\n"
            f"(Forwarded to {context['owner'] or 'unassigned agent'})"
        )

    async def _handle_browser(self, args: list[str]) -> str:
        """Handle /browser <url> - open URL in desktop browser."""
        if not args:
            return "Usage: /browser <url>"

        url = args[0]
        if not self.desktop_api:
            return f"Desktop API not configured. Would open: {url}"

        result = self.desktop_api.open_browser(url)
        return f"Browser: {result.get('status', 'unknown')} - {url}"

    async def _handle_screenshot(self, args: list[str]) -> str:
        """Handle /screenshot - capture desktop screenshot."""
        if not self.desktop_api:
            return "Desktop API not configured."

        result = self.desktop_api.screenshot()
        # Return a text indicator; actual image handling is Gateway-level
        return "Screenshot captured. (Image delivery not yet implemented in Phase 0)"

    async def _handle_commit(self, args: list[str]) -> str:
        """Handle /commit <msg> - placeholder for git commit."""
        task_id = self.task_switcher.get_active_task()
        if not task_id:
            return "No active task. Use /switch first."
        return f"Git commit on {task_id}: {' '.join(args)} (adapter not yet connected)"

    async def _handle_test(self, args: list[str]) -> str:
        """Handle /test [pattern] - placeholder for running tests."""
        task_id = self.task_switcher.get_active_task()
        if not task_id:
            return "No active task. Use /switch first."
        return f"Run tests on {task_id}: {' '.join(args) or 'all'} (adapter not yet connected)"

    async def _handle_unknown(self, cmd: str) -> str:
        """Return help for unknown commands."""
        return (
            f"Unknown command: /{cmd}\n\n"
            "Available commands:\n"
            "  /switch [task] - switch to a task\n"
            "  /status - show all tasks\n"
            "  /ask <question> - ask about current task\n"
            "  /browser <url> - open URL on desktop\n"
            "  /screenshot - capture screen\n"
            "  /commit <msg> - git commit (Phase 1)\n"
            "  /test [pattern] - run tests (Phase 1)"
        )

    async def _format_output(self, text: str) -> str:
        """Truncate output to Telegram's max message length."""
        if len(text) <= TELEGRAM_MAX_LENGTH:
            return text

        truncation_notice = f"\n\n... ({len(text) - TELEGRAM_MAX_LENGTH + 50} chars truncated)"
        max_content = TELEGRAM_MAX_LENGTH - len(truncation_notice)
        return text[:max_content] + truncation_notice
