"""Tests for CLI Hook — wraps CLI tools and triggers notifications on failure.

Design decisions tested:
- Reads MUON_TASK_ID / MUON_AGENT_NAME from environment variables
- Executes wrapped command via subprocess
- Captures exit code and stderr
- On failure (exit_code != 0): sends critical notification via HTTP POST
- On success with MUON_NOTIFY_ON_DONE=true: sends normal notification
- Zero-config: all settings from env vars, no config files needed
"""

import pytest
from unittest.mock import patch, MagicMock
import os
import json

from scripts.cli_notify import CLINotifier, main


# Helper: manual env management (patch.dict fails on Windows with large env)
def _clear_muon_env():
    """Remove all MUON_ env vars."""
    for key in list(os.environ.keys()):
        if key.startswith("MUON_"):
            os.environ.pop(key, None)


def _set_env(**kwargs):
    """Set env vars, clear others. Returns nothing."""
    _clear_muon_env()
    for key, value in kwargs.items():
        os.environ[key] = value


class TestEnvVarReading:
    """Tests for environment variable parsing."""

    def test_reads_task_id(self):
        _set_env(MUON_TASK_ID="task-42")
        notifier = CLINotifier()
        assert notifier.task_id == "task-42"

    def test_reads_agent_name(self):
        _set_env(MUON_AGENT_NAME="hermes")
        notifier = CLINotifier()
        assert notifier.agent == "hermes"

    def test_reads_notify_flags(self):
        _set_env(MUON_NOTIFY_ON_ERROR="true", MUON_NOTIFY_ON_DONE="true")
        notifier = CLINotifier()
        assert notifier.notify_on_error is True
        assert notifier.notify_on_done is True

    def test_defaults_when_env_missing(self):
        _clear_muon_env()
        notifier = CLINotifier()
        assert notifier.task_id is None
        assert notifier.agent is None
        assert notifier.notify_on_error is True  # default
        assert notifier.notify_on_done is False  # default


class TestCommandExecution:
    """Tests for wrapping and executing CLI commands."""

    @pytest.fixture
    def notifier(self):
        _set_env(
            MUON_TASK_ID="task-42",
            MUON_AGENT_NAME="hermes",
            MUON_NOTIFY_ON_ERROR="true",
            MUON_NOTIFY_ON_DONE="false"
        )
        return CLINotifier()

    @patch("subprocess.run")
    def test_runs_command_and_returns_exit_code(self, mock_run, notifier):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        exit_code, stdout, stderr = notifier.run(["echo", "hello"])

        assert exit_code == 0
        assert stdout == "ok"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["echo", "hello"]

    @patch("subprocess.run")
    def test_failure_exit_code(self, mock_run, notifier):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")
        exit_code, stdout, stderr = notifier.run(["false"])

        assert exit_code == 1
        assert stderr == "error msg"


class TestNotificationTriggering:
    """Tests for HTTP notification on failure/success."""

    @pytest.fixture
    def notifier(self):
        _set_env(
            MUON_TASK_ID="task-42",
            MUON_AGENT_NAME="hermes",
            MUON_NOTIFY_ON_ERROR="true",
            MUON_NOTIFY_ON_DONE="true",
            MUON_HUB_URL="http://localhost:8001/notify"
        )
        return CLINotifier()

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_failure_sends_critical_notification(self, mock_run, mock_urlopen, notifier):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="test failed")
        mock_urlopen.return_value.__enter__.return_value = MagicMock()

        exit_code = notifier.execute(["npm", "test"])

        assert exit_code == 1
        mock_urlopen.assert_called_once()
        # Check the request was POST with correct payload
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.method == "POST"
        data = json.loads(req.data)
        assert data["level"] == "critical"
        assert data["task_id"] == "task-42"
        assert data["agent"] == "hermes"
        assert "test failed" in data["message"]

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_success_sends_normal_when_enabled(self, mock_run, mock_urlopen, notifier):
        mock_run.return_value = MagicMock(returncode=0, stdout="passing", stderr="")
        mock_urlopen.return_value.__enter__.return_value = MagicMock()

        exit_code = notifier.execute(["npm", "test"])

        assert exit_code == 0
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        data = json.loads(req.data)
        assert data["level"] == "normal"

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_success_no_notification_when_disabled(self, mock_run, mock_urlopen, notifier):
        notifier.notify_on_done = False
        mock_run.return_value = MagicMock(returncode=0, stdout="passing", stderr="")

        exit_code = notifier.execute(["npm", "test"])

        assert exit_code == 0
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_notification_error_does_not_crash(self, mock_run, mock_urlopen, notifier):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        mock_urlopen.side_effect = Exception("Connection refused")

        # Should not raise
        exit_code = notifier.execute(["npm", "test"])
        assert exit_code == 1


class TestNoTaskEnv:
    """Tests when no task environment is set."""

    @patch("subprocess.run")
    def test_runs_command_without_notification(self, mock_run):
        _clear_muon_env()
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        notifier = CLINotifier()

        exit_code = notifier.execute(["echo", "hi"])

        assert exit_code == 0
        assert notifier.task_id is None
