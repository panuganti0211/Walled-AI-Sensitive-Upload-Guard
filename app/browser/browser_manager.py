"""Browser process manager for standalone managed Chromium instances.

Launches Microsoft Edge or Google Chrome on Windows with an isolated application profile
and enables Chrome DevTools Protocol (CDP) strictly bound to localhost.
"""

import atexit
import os
import socket
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import psutil

from app.browser.models import BrowserStatus


# Standard Windows installation paths
DEFAULT_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

DEFAULT_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


class BrowserManager:
    """Manages the lifecycle of a dedicated, managed Chromium browser instance."""

    def __init__(self, profile_dir: Optional[Path] = None):
        # Dedicated, isolated user data directory to preserve user logins
        # without touching or interfering with the user's personal browser profiles
        if profile_dir:
            self.profile_dir = Path(profile_dir)
        else:
            # Default to dedicated workspace folder 'browser_profile' (excluded by .gitignore)
            project_root = Path(__file__).resolve().parent.parent.parent
            self.profile_dir = project_root / "browser_profile"

        try:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        self._process: Optional[subprocess.Popen] = None
        self._cdp_port: Optional[int] = None
        self._browser_name: Optional[str] = None
        self._status: BrowserStatus = BrowserStatus.NOT_LAUNCHED

        # Automatically clean up browser processes when application exits
        atexit.register(self.stop_browser)

    @property
    def status(self) -> BrowserStatus:
        """Current status of the managed browser."""
        if self._process:
            if self._process.poll() is None:
                return BrowserStatus.RUNNING
            else:
                return BrowserStatus.DISCONNECTED
        return self._status

    @property
    def cdp_port(self) -> Optional[int]:
        """The active localhost CDP port if browser is running."""
        return self._cdp_port

    @property
    def browser_name(self) -> Optional[str]:
        """Name of the currently selected/launched browser."""
        return self._browser_name

    def find_installed_browsers(self) -> Dict[str, Optional[str]]:
        """Detect installed Edge and Chrome browser executables on Windows.

        Returns:
            Dict mapping 'edge' and 'chrome' to their executable path or None.
        """
        installed: Dict[str, Optional[str]] = {"edge": None, "chrome": None}

        for path in DEFAULT_EDGE_PATHS:
            if os.path.isfile(path):
                installed["edge"] = path
                break

        for path in DEFAULT_CHROME_PATHS:
            if os.path.isfile(path):
                installed["chrome"] = path
                break

        return installed

    @staticmethod
    def get_free_localhost_port() -> int:
        """Allocate an available TCP port bound strictly to localhost (127.0.0.1)."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def build_launch_command(
        self,
        browser_key: str,
        port: int,
        urls: Optional[List[str]] = None,
    ) -> List[str]:
        """Construct the launch argument list with strict security constraints."""
        browsers = self.find_installed_browsers()
        executable = browsers.get(browser_key.lower())

        if not executable:
            raise FileNotFoundError(f"Browser '{browser_key}' is not installed or not found.")

        target_urls = urls or [
            "https://chatgpt.com",
            "https://www.perplexity.ai",
        ]

        # Security flags:
        # - Strictly bind CDP to localhost 127.0.0.1 (never 0.0.0.0)
        # - Use dedicated application profile directory
        # - Do not disable TLS certificate checks or standard web security
        cmd = [
            executable,
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={str(self.profile_dir.resolve())}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        cmd.extend(target_urls)
        return cmd

    def launch_browser(
        self,
        browser_key: str = "edge",
        urls: Optional[List[str]] = None,
        port: Optional[int] = None,
    ) -> bool:
        """Launch a managed browser session with remote debugging.

        Args:
            browser_key: 'edge' (default) or 'chrome'.
            urls: Target URLs to open upon launch.
            port: Optional fixed port, or dynamically allocated if None.

        Returns:
            True if process started successfully, False otherwise.
        """
        if self.is_running():
            self.stop_browser()

        self._status = BrowserStatus.STARTING
        self._cdp_port = port or self.get_free_localhost_port()
        self._browser_name = browser_key

        try:
            cmd = self.build_launch_command(browser_key, self._cdp_port, urls)
            # Launch detached from console window but monitored by parent process
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._status = BrowserStatus.RUNNING
            return True
        except Exception:
            self._status = BrowserStatus.ERROR
            self._process = None
            self._cdp_port = None
            return False

    def is_running(self) -> bool:
        """Check if the managed browser process is currently active."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def stop_browser(self) -> None:
        """Safely terminate the managed browser and any child processes."""
        if not self._process:
            self._status = BrowserStatus.NOT_LAUNCHED
            return

        pid = self._process.pid
        try:
            # Terminate child processes to avoid orphaned browser utility tasks
            if psutil.pid_exists(pid):
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                parent.terminate()
                parent.wait(timeout=3)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass
        finally:
            self._process = None
            self._cdp_port = None
            self._status = BrowserStatus.DISCONNECTED
