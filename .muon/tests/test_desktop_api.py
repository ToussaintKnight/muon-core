"""Tests for Desktop API — cross-platform desktop control via HTTP.

Design decisions tested:
- Abstract base class (DesktopAPI) cannot be instantiated directly
- MacDesktopAPI uses subprocess + AppleScript
- FastAPI endpoints delegate to platform implementation
- Screenshot returns base64-encoded PNG
- Errors are caught and returned as HTTP 500 with detail
- Platform auto-detected via sys.platform
"""

import pytest
from unittest.mock import patch, MagicMock
import base64
import sys

from src.desktop_api import DesktopAPI, MacDesktopAPI, WinDesktopAPI, create_desktop_api


class TestAbstractBase:
    """Tests for the abstract base class."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            DesktopAPI()

    def test_subclass_must_implement_methods(self):
        class Incomplete(DesktopAPI):
            pass

        with pytest.raises(TypeError):
            Incomplete()


class TestMacDesktopAPI:
    """Tests for Mac AppleScript implementation."""

    @pytest.fixture
    def mac(self):
        return MacDesktopAPI()

    @patch("subprocess.run")
    def test_open_browser_calls_osascript(self, mock_run, mac):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = mac.open_browser("https://github.com")

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "osascript" in args
        assert "https://github.com" in str(args)
        assert result["status"] == "opened"
        assert result["url"] == "https://github.com"

    @patch("subprocess.run")
    def test_focus_window_calls_system_events(self, mock_run, mac):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = mac.focus_window("Google Chrome")

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "System Events" in str(args)
        assert result["status"] == "focused"
        assert result["app"] == "Google Chrome"

    @patch("subprocess.run")
    @patch("builtins.open", create=True)
    @patch("os.path.exists")
    @patch("os.remove")
    def test_screenshot_reads_jpeg_file(self, mock_remove, mock_exists, mock_open_fn, mock_run, mac):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_exists.return_value = True
        mock_file = MagicMock()
        mock_file.read.return_value = b"fake_jpg_data"
        mock_open_fn.return_value.__enter__.return_value = mock_file

        result = mac.screenshot()

        # screencapture + sips = 2 subprocess calls
        assert mock_run.call_count == 2
        first_call = mock_run.call_args_list[0][0][0]
        second_call = mock_run.call_args_list[1][0][0]
        assert "screencapture" in str(first_call)
        assert "sips" in str(second_call)
        assert result["image_b64"] == base64.b64encode(b"fake_jpg_data").decode()
        assert result["format"] == "jpeg"

    @patch("subprocess.run")
    def test_applescript_error_returns_error_dict(self, mock_run, mac):
        from subprocess import CalledProcessError
        mock_run.side_effect = CalledProcessError(
            returncode=1, cmd=["osascript"], stderr="permission denied"
        )
        result = mac.open_browser("https://example.com")

        assert result["status"] == "error"
        assert "permission denied" in result["error"]


class TestWinDesktopAPI:
    """Tests for Windows PowerShell implementation."""

    @pytest.fixture
    def win(self):
        return WinDesktopAPI()

    @patch("subprocess.run")
    def test_open_browser_calls_start_process(self, mock_run, win):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = win.open_browser("https://github.com")

        mock_run.assert_called_once()
        assert "Start-Process" in str(mock_run.call_args[0][0])
        assert result["status"] == "opened"

    @patch("subprocess.run")
    def test_focus_window_error_returns_dict(self, mock_run, win):
        from subprocess import CalledProcessError
        mock_run.side_effect = CalledProcessError(
            returncode=1, cmd=["powershell"], stderr="not found"
        )
        result = win.focus_window("Chrome")

        assert result["status"] == "error"


class TestFactory:
    """Tests for platform auto-detection factory."""

    @patch("sys.platform", "darwin")
    def test_darwin_returns_mac(self):
        api = create_desktop_api()
        assert isinstance(api, MacDesktopAPI)

    @patch("sys.platform", "win32")
    def test_win32_returns_win(self):
        api = create_desktop_api()
        assert isinstance(api, WinDesktopAPI)

    @patch("sys.platform", "linux")
    def test_linux_raises(self):
        with pytest.raises(RuntimeError, match="Unsupported platform"):
            create_desktop_api()


class TestFastAPIEndpoints:
    """Tests for FastAPI HTTP endpoints."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from src.desktop_api import app

        # Override the module-level desktop_api with a mock
        mock_desktop = MagicMock()
        mock_desktop.open_browser.return_value = {"status": "opened", "url": "https://github.com"}
        mock_desktop.screenshot.return_value = {"image_b64": "aGVsbG8="}
        mock_desktop.focus_window.return_value = {"status": "focused", "app": "Chrome"}

        with patch.dict("src.desktop_api.__dict__", {"desktop_api": mock_desktop}):
            yield TestClient(app)

    def test_browser_endpoint(self, client):
        response = client.post("/browser", json={"url": "https://github.com"})
        assert response.status_code == 200
        assert response.json()["status"] == "opened"

    def test_screenshot_endpoint(self, client):
        response = client.post("/screenshot")
        assert response.status_code == 200
        assert "image_b64" in response.json()

    def test_focus_endpoint(self, client):
        response = client.post("/focus", json={"app_name": "Chrome"})
        assert response.status_code == 200
        assert response.json()["status"] == "focused"

    def test_browser_missing_url_returns_422(self, client):
        response = client.post("/browser", json={})
        assert response.status_code == 422

    def test_focus_missing_app_returns_422(self, client):
        response = client.post("/focus", json={})
        assert response.status_code == 422
