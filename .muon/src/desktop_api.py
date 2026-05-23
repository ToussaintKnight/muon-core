"""Desktop API — cross-platform desktop control via FastAPI.

Design decisions:
- Abstract base class (DesktopAPI) for cross-platform extensibility
- MacDesktopAPI uses AppleScript via subprocess (osascript, screencapture)
- WinDesktopAPI uses PowerShell via subprocess (Start-Process, .NET Graphics)
- FastAPI runs as independent process on configurable port (default 8001)
- Screenshot returns base64-encoded PNG for Telegram sendPhoto API
- Errors are caught and returned as JSON with status="error"
- Factory function auto-detects platform via sys.platform
"""

import base64
import logging
import os
import subprocess
import sys
from abc import ABC, abstractmethod

from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI()


class BrowserRequest(BaseModel):
    url: str


class FocusRequest(BaseModel):
    app_name: str


class DesktopAPI(ABC):
    """Abstract base for cross-platform desktop control."""

    @abstractmethod
    def open_browser(self, url: str) -> dict:
        """Open a URL in the default browser."""

    @abstractmethod
    def screenshot(self) -> dict:
        """Capture a screenshot and return base64-encoded PNG."""

    @abstractmethod
    def focus_window(self, title: str) -> dict:
        """Bring an application window to the foreground."""


class MacDesktopAPI(DesktopAPI):
    """macOS implementation using AppleScript and screencapture."""

    def open_browser(self, url: str) -> dict:
        try:
            subprocess.run(
                ["osascript", "-e", f'open location "{url}"'],
                check=True, capture_output=True, text=True
            )
            return {"status": "opened", "url": url}
        except subprocess.CalledProcessError as e:
            logger.error("Failed to open browser: %s", e.stderr)
            return {"status": "error", "error": e.stderr or "AppleScript failed"}

    def screenshot(self) -> dict:
        path = "/tmp/muon_screenshot.png"
        try:
            subprocess.run(
                ["screencapture", path],
                check=True, capture_output=True, text=True
            )
            if not os.path.exists(path):
                return {"status": "error", "error": "Screenshot file not created"}

            with open(path, "rb") as f:
                img_bytes = f.read()
            return {"image_b64": base64.b64encode(img_bytes).decode()}
        except subprocess.CalledProcessError as e:
            logger.error("Failed to capture screenshot: %s", e.stderr)
            return {"status": "error", "error": e.stderr or "screencapture failed"}

    def focus_window(self, title: str) -> dict:
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to tell process "{title}" to set frontmost to true'],
                check=True, capture_output=True, text=True
            )
            return {"status": "focused", "app": title}
        except subprocess.CalledProcessError as e:
            logger.error("Failed to focus window: %s", e.stderr)
            return {"status": "error", "error": e.stderr or "AppleScript failed"}


class WinDesktopAPI(DesktopAPI):
    """Windows implementation using PowerShell."""

    def open_browser(self, url: str) -> dict:
        try:
            subprocess.run(
                ["powershell", "-Command", f'Start-Process chrome "{url}"'],
                check=True, capture_output=True, text=True
            )
            return {"status": "opened", "url": url}
        except subprocess.CalledProcessError as e:
            logger.error("Failed to open browser: %s", e.stderr)
            return {"status": "error", "error": e.stderr or "PowerShell failed"}

    def screenshot(self) -> dict:
        path = os.path.expanduser("~\\AppData\\Local\\Temp\\muon_screenshot.png")
        ps_script = (
            f'Add-Type -AssemblyName System.Drawing; '
            f'$bmp = New-Object System.Drawing.Bitmap([System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width, '
            f'[System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height); '
            f'$graphics = [System.Drawing.Graphics]::FromImage($bmp); '
            f'$graphics.CopyFromScreen(0, 0, 0, 0, $bmp.Size); '
            f'$bmp.Save("{path}"); '
            f'$graphics.Dispose(); $bmp.Dispose()'
        )
        try:
            subprocess.run(
                ["powershell", "-Command", ps_script],
                check=True, capture_output=True, text=True
            )
            if not os.path.exists(path):
                return {"status": "error", "error": "Screenshot file not created"}

            with open(path, "rb") as f:
                img_bytes = f.read()
            return {"image_b64": base64.b64encode(img_bytes).decode()}
        except subprocess.CalledProcessError as e:
            logger.error("Failed to capture screenshot: %s", e.stderr)
            return {"status": "error", "error": e.stderr or "PowerShell failed"}

    def focus_window(self, title: str) -> dict:
        ps_script = (
            f'$proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like "*{title}*" }}; '
            f'if ($proc) {{ '
            f'  Add-Type @"\n'
            f'  using System;\n'
            f'  using System.Runtime.InteropServices;\n'
            f'  public class WinAPI {{\n'
            f'    [DllImport("user32.dll")]\n'
            f'    public static extern bool SetForegroundWindow(IntPtr hWnd);\n'
            f'  }}\n'
            f'  "@; '
            f'  [WinAPI]::SetForegroundWindow($proc.MainWindowHandle) '
            f'}} else {{ Write-Error "Process not found" }}'
        )
        try:
            subprocess.run(
                ["powershell", "-Command", ps_script],
                check=True, capture_output=True, text=True
            )
            return {"status": "focused", "app": title}
        except subprocess.CalledProcessError as e:
            logger.error("Failed to focus window: %s", e.stderr)
            return {"status": "error", "error": e.stderr or "PowerShell failed"}


def create_desktop_api() -> DesktopAPI:
    """Factory: auto-detect platform and return appropriate implementation."""
    if sys.platform == "darwin":
        return MacDesktopAPI()
    elif sys.platform == "win32":
        return WinDesktopAPI()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")


# Global instance (created at import time for FastAPI endpoints)
desktop_api = create_desktop_api()


@app.post("/browser")
def browser_endpoint(request: BrowserRequest):
    return desktop_api.open_browser(request.url)


@app.post("/screenshot")
def screenshot_endpoint():
    return desktop_api.screenshot()


@app.post("/focus")
def focus_endpoint(request: FocusRequest):
    return desktop_api.focus_window(request.app_name)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("MUON_DESKTOP_PORT", "8001"))
    host = os.environ.get("MUON_DESKTOP_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
