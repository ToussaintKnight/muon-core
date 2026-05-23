#!/usr/bin/env python3
"""CLI Hook — wraps CLI tools and triggers notifications on failure.

Design decisions:
- Reads all configuration from environment variables (zero config files)
- Executes wrapped command via subprocess, capturing stdout/stderr/exit code
- On failure (exit_code != 0): sends critical notification via HTTP POST
- On success with MUON_NOTIFY_ON_DONE=true: sends normal notification
- Notification errors are logged, not raised — CLI exit code is always preserved
- Uses urllib (stdlib) to avoid external dependencies in the wrapper script

Usage:
    cli_notify kimicode /test
    cli_notify npm test
    MUON_NOTIFY_ON_DONE=true cli_notify pytest

Environment variables:
    MUON_TASK_ID          — current task ID (set by Task Switcher)
    MUON_AGENT_NAME       — current agent name (set by Task Switcher)
    MUON_NOTIFY_ON_ERROR  — "true" to send critical on failure (default: true)
    MUON_NOTIFY_ON_DONE   — "true" to send normal on success (default: false)
    MUON_HUB_URL          — Notification Hub endpoint (default: http://localhost:8001/notify)
"""

import json
import logging
import os
import subprocess
import sys
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_HUB_URL = "http://localhost:8001/notify"


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse boolean environment variable."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.lower().strip()
    if value in ("true", "1", "yes", "on"):
        return True
    if value in ("false", "0", "no", "off", ""):
        return False
    return default


class CLINotifier:
    """Wraps CLI commands and sends notifications based on exit code."""

    def __init__(self):
        self.task_id = os.environ.get("MUON_TASK_ID") or None
        self.agent = os.environ.get("MUON_AGENT_NAME") or None
        self.notify_on_error = _env_bool("MUON_NOTIFY_ON_ERROR", default=True)
        self.notify_on_done = _env_bool("MUON_NOTIFY_ON_DONE", default=False)
        self.hub_url = os.environ.get("MUON_HUB_URL", DEFAULT_HUB_URL)

    def run(self, command: list[str]) -> tuple[int, str, str]:
        """Run a command and return (exit_code, stdout, stderr)."""
        result = subprocess.run(
            command,
            capture_output=True,
            text=True
        )
        return result.returncode, result.stdout, result.stderr

    def _send_notification(self, level: str, message: str) -> bool:
        """Send notification via HTTP POST to Notification Hub.

        Returns True if sent successfully, False otherwise.
        Errors are logged, not raised.
        """
        if not self.task_id:
            logger.debug("No MUON_TASK_ID set, skipping notification")
            return False

        payload = {
            "level": level,
            "task_id": self.task_id,
            "agent": self.agent or "unknown",
            "message": message,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.hub_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("Failed to send %s notification: %s", level, e)
            return False

    def execute(self, command: list[str]) -> int:
        """Execute a command and optionally send notifications.

        Returns the command's exit code (always preserved).
        """
        exit_code, stdout, stderr = self.run(command)
        cmd_str = " ".join(command)

        if exit_code != 0 and self.notify_on_error:
            message = f"Command failed: {cmd_str}\nExit code: {exit_code}"
            if stderr:
                message += f"\nStderr: {stderr[:500]}"
            self._send_notification("critical", message)

        elif exit_code == 0 and self.notify_on_done:
            message = f"Command completed: {cmd_str}"
            if stdout:
                message += f"\nOutput: {stdout[:500]}"
            self._send_notification("normal", message)

        # Print stdout/stderr to preserve normal CLI behavior
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)

        return exit_code


def main():
    """Entry point for command-line usage."""
    if len(sys.argv) < 2:
        print("Usage: cli_notify <command> [args...]", file=sys.stderr)
        sys.exit(1)

    notifier = CLINotifier()
    exit_code = notifier.execute(sys.argv[1:])
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
