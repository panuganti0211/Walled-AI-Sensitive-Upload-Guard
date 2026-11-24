"""Foundation tests verifying environment, packages, and main window instantiation."""

import os
import sys
import pytest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config.settings import config
from app.desktop.main_window import MainWindow
from app.main import create_app


def test_config_defaults():
    """Verify default DLP configuration values."""
    assert config.app_name == "Walled AI Sensitive Upload Guard"
    assert config.sensitive_marker == "WALLED_SENSITIVE"
    assert "chatgpt.com" in config.target_domains
    assert any("perplexity.ai" in domain for domain in config.target_domains)
    assert ".txt" in config.supported_file_extensions
    assert ".pdf" in config.supported_file_extensions


def test_main_window_instantiation(qtbot):
    """Verify PySide6 QApplication and MainWindow instantiate cleanly without errors."""
    app = create_app()
    assert app is not None

    window = MainWindow()
    qtbot.addWidget(window)

    assert "Walled AI Sensitive Upload Guard" in window.windowTitle()
    assert window.card_protection is not None
    assert window.card_chatgpt is not None
    assert window.card_perplexity is not None
    assert window.card_detections is not None
