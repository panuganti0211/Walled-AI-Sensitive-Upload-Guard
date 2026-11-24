"""Unit tests for the managed Chromium browser manager."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.browser.browser_manager import BrowserManager
from app.browser.models import BrowserStatus


class TestBrowserManager:
    """Test suite for BrowserManager process and profile handling."""

    @pytest.fixture
    def manager(self, tmp_path):
        return BrowserManager(profile_dir=tmp_path / "test_profile")

    def test_find_installed_browsers_keys(self, manager):
        """Verify browser detector checks for both Edge and Chrome."""
        browsers = manager.find_installed_browsers()
        assert "edge" in browsers
        assert "chrome" in browsers

    def test_build_launch_command_security_flags(self, manager):
        """Verify launch command enforces localhost binding and dedicated profile."""
        with patch.object(manager, "find_installed_browsers", return_value={"edge": "msedge.exe"}):
            cmd = manager.build_launch_command("edge", port=9222)

            # Security assertions
            assert "--remote-debugging-address=127.0.0.1" in cmd
            assert "--remote-debugging-port=9222" in cmd
            assert any("--user-data-dir=" in arg for arg in cmd)
            assert "https://chatgpt.com" in cmd
            assert "https://www.perplexity.ai" in cmd

    def test_get_free_localhost_port(self):
        """Verify dynamic localhost port allocation returns valid ephemeral port."""
        port = BrowserManager.get_free_localhost_port()
        assert isinstance(port, int)
        assert port > 1024

    def test_missing_browser_raises_file_not_found(self, manager):
        """Verify attempting to launch an uninstalled browser raises FileNotFoundError."""
        with patch.object(manager, "find_installed_browsers", return_value={"edge": None, "chrome": None}):
            with pytest.raises(FileNotFoundError):
                manager.build_launch_command("edge", port=9222)

    def test_stop_browser_safe_when_not_running(self, manager):
        """Verify stop_browser handles stopped or uninitialized states gracefully."""
        manager.stop_browser()
        assert manager.is_running() is False
        assert manager.status == BrowserStatus.NOT_LAUNCHED

    def test_launch_browser_mock_success(self, manager):
        """Verify launch_browser tracks process and updates status."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # running
        mock_proc.pid = 9999

        with patch.object(manager, "build_launch_command", return_value=["browser.exe"]), \
             patch("subprocess.Popen", return_value=mock_proc):
            success = manager.launch_browser("edge", port=9333)
            assert success is True
            assert manager.is_running() is True
            assert manager.status == BrowserStatus.RUNNING
            assert manager.cdp_port == 9333

            # Test stop
            manager.stop_browser()
            assert manager.is_running() is False
