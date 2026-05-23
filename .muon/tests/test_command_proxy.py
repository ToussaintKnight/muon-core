"""
Test Driven Development for Command Proxy.

Tests cover:
- Command parsing and routing (/switch, /status, /ask, /browser, /screenshot, /commit, /test)
- Integration with Task Switcher (active task resolution)
- Error handling (unknown commands, missing tasks)
- Output formatting (truncation for Telegram 4096 limit)
"""

import pytest
from unittest.mock import Mock, AsyncMock
from src.command_proxy import CommandProxy


@pytest.fixture
def mock_task_switcher():
    switcher = Mock()
    switcher.get_active_task.return_value = "task-42"
    switcher.get_task.return_value = {
        "task_id": "task-42",
        "project": "muon-core",
        "branch": "feature/auth",
        "worktree_path": "/projects/muon-core--feature-auth",
        "assigned_agent": "kimicode",
        "status": "active"
    }
    switcher.list_tasks.return_value = [
        {"task_id": "task-42", "project": "muon-core", "status": "active", "assigned_agent": "kimicode"},
        {"task_id": "task-43", "project": "other", "status": "pending", "assigned_agent": "claude"}
    ]
    switcher.switch.return_value = {
        "task_id": "task-42",
        "project": "muon-core",
        "branch": "feature/auth",
        "agent": "kimicode",
        "git_status": "M  src/auth.py"
    }
    return switcher


@pytest.fixture
def mock_context_registry():
    registry = Mock()
    registry.get_context.return_value = {
        "summary": "Auth refactor",
        "detail": "OAuth2 config needs update",
        "full": None,
        "hash": "abc123",
        "owner": "kimicode"
    }
    return registry


@pytest.fixture
def mock_desktop_api():
    api = Mock()
    api.open_browser.return_value = {"status": "opened", "url": "http://100.x:3000"}
    api.screenshot.return_value = {"image_b64": "base64data..."}
    return api


@pytest.fixture
def proxy(mock_task_switcher, mock_context_registry, mock_desktop_api):
    return CommandProxy(
        task_switcher=mock_task_switcher,
        context_registry=mock_context_registry,
        desktop_api=mock_desktop_api
    )


class TestCommandParsing:
    """Tests for basic command parsing."""

    def test_parses_command_name(self, proxy):
        cmd, args = proxy._parse("/switch muon-core")
        assert cmd == "switch"
        assert args == ["muon-core"]

    def test_parses_command_with_multiple_args(self, proxy):
        cmd, args = proxy._parse("/commit -m fix bug")
        assert cmd == "commit"
        assert args == ["-m", "fix", "bug"]

    def test_parses_command_without_args(self, proxy):
        cmd, args = proxy._parse("/status")
        assert cmd == "status"
        assert args == []

    def test_strips_extra_spaces(self, proxy):
        cmd, args = proxy._parse("/switch   muon-core")
        assert cmd == "switch"
        assert args == ["muon-core"]


class TestSwitchCommand:
    """Tests for /switch command routing."""

    @pytest.mark.asyncio
    async def test_switch_delegates_to_task_switcher(self, proxy, mock_task_switcher):
        result = await proxy.handle("/switch muon-core")
        mock_task_switcher.switch.assert_called_once_with("muon-core")
        assert "muon-core" in result

    @pytest.mark.asyncio
    async def test_switch_no_args_lists_tasks(self, proxy, mock_task_switcher):
        result = await proxy.handle("/switch")
        mock_task_switcher.list_tasks.assert_called_once()
        assert "task-42" in result


class TestStatusCommand:
    """Tests for /status command."""

    @pytest.mark.asyncio
    async def test_status_shows_all_tasks(self, proxy, mock_task_switcher):
        result = await proxy.handle("/status")
        mock_task_switcher.list_tasks.assert_called_once()
        assert "task-42" in result
        assert "kimicode" in result


class TestAskCommand:
    """Tests for /ask command."""

    @pytest.mark.asyncio
    async def test_ask_without_task_uses_active(self, proxy, mock_task_switcher, mock_context_registry):
        result = await proxy.handle("/ask how to fix this")
        mock_task_switcher.get_active_task.assert_called_once()
        mock_context_registry.get_context.assert_called_once_with("task-42", tier=2)
        assert "Auth refactor" in result  # from mock context summary

    @pytest.mark.asyncio
    async def test_ask_no_active_task_shows_error(self, proxy, mock_task_switcher):
        mock_task_switcher.get_active_task.return_value = None
        result = await proxy.handle("/ask how to fix")
        assert "no active task" in result.lower() or "switch" in result.lower()


class TestBrowserCommand:
    """Tests for /browser command."""

    @pytest.mark.asyncio
    async def test_browser_delegates_to_desktop_api(self, proxy, mock_desktop_api):
        result = await proxy.handle("/browser http://100.x:3000")
        mock_desktop_api.open_browser.assert_called_once_with("http://100.x:3000")
        assert "opened" in result

    @pytest.mark.asyncio
    async def test_browser_no_url_shows_error(self, proxy):
        result = await proxy.handle("/browser")
        assert "url" in result.lower()


class TestScreenshotCommand:
    """Tests for /screenshot command."""

    @pytest.mark.asyncio
    async def test_screenshot_delegates_to_desktop_api(self, proxy, mock_desktop_api):
        result = await proxy.handle("/screenshot")
        mock_desktop_api.screenshot.assert_called_once()
        assert "screenshot" in result.lower()


class TestUnknownCommand:
    """Tests for unknown commands."""

    @pytest.mark.asyncio
    async def test_unknown_command_returns_help(self, proxy):
        result = await proxy.handle("/randomcmd")
        assert "unknown" in result.lower()
        assert "/switch" in result
        assert "/status" in result


class TestOutputFormatting:
    """Tests for Telegram output constraints."""

    @pytest.mark.asyncio
    async def test_long_output_truncated(self, proxy):
        long_text = "x" * 5000
        result = await proxy._format_output(long_text)
        assert len(result) <= 4096
        assert "..." in result

    @pytest.mark.asyncio
    async def test_short_output_not_truncated(self, proxy):
        short_text = "short message"
        result = await proxy._format_output(short_text)
        assert result == short_text


class TestErrorHandling:
    """Tests for graceful error handling."""

    @pytest.mark.asyncio
    async def test_switch_raises_returns_error_message(self, proxy, mock_task_switcher):
        mock_task_switcher.switch.side_effect = KeyError("not found")
        result = await proxy.handle("/switch bad-task")
        assert "error" in result.lower() or "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_desktop_api_error_returns_error_message(self, proxy, mock_desktop_api):
        mock_desktop_api.open_browser.side_effect = Exception("connection refused")
        result = await proxy.handle("/browser http://100.x:3000")
        assert "error" in result.lower()
