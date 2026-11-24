"""Unit tests for the AI response text styler (Phase 6)."""

from unittest.mock import MagicMock, patch
import pytest

from app.browser.cdp_client import CDPClient, TabSession
from app.browser.response_styler import (
    CHATGPT_ASSISTANT_SELECTORS,
    PERPLEXITY_ANSWER_SELECTORS,
    PROHIBITED_USER_SELECTORS,
    STYLE_ELEMENT_ID,
    ResponseStyler,
)
from app.config.settings import config


class TestResponseStyler:
    """Test suite for ResponseStyler CSS and JS generation."""

    def test_default_color_from_config(self):
        """Verify styler defaults to config.ai_response_color."""
        styler = ResponseStyler()
        assert styler.color == config.ai_response_color
        css = styler.generate_css()
        assert config.ai_response_color in css

    def test_custom_color_override(self):
        """Verify custom color overrides default and propagates to CSS and JS."""
        custom_hex = "#10B981"
        styler = ResponseStyler(color=custom_hex)
        assert styler.color == custom_hex

        css = styler.generate_css()
        assert custom_hex in css

        js = styler.generate_injection_script()
        assert custom_hex in js

        # Test dynamic property setter
        new_hex = "#EF4444"
        styler.color = new_hex
        assert new_hex in styler.generate_css()

    def test_chatgpt_assistant_selectors_present(self):
        """Verify ChatGPT assistant message selectors are included."""
        styler = ResponseStyler()
        css = styler.generate_css()

        for sel in CHATGPT_ASSISTANT_SELECTORS:
            assert sel in css, f"Expected selector '{sel}' in generated CSS"

    def test_perplexity_answer_selectors_present(self):
        """Verify Perplexity answer markdown selectors are included."""
        styler = ResponseStyler()
        css = styler.generate_css()

        for sel in PERPLEXITY_ANSWER_SELECTORS:
            assert sel in css, f"Expected selector '{sel}' in generated CSS"

    def test_prohibited_selectors_not_colored(self):
        """Verify user prompts, input elements, and navigation are NEVER given highlight color."""
        styler = ResponseStyler()
        css = styler.generate_css()

        for prohibited in PROHIBITED_USER_SELECTORS:
            # None of these should have color applied as a rule target
            assert f"{prohibited} {{" not in css
            assert f"{prohibited}," not in css

    def test_code_block_color_preservation(self):
        """Verify code blocks within assistant responses preserve code highlighting."""
        styler = ResponseStyler()
        css = styler.generate_css()
        assert "pre code" in css
        assert "color: inherit;" in css

    def test_javascript_injection_script_structure(self):
        """Verify the JavaScript script contains guards, persistent style tag, and MutationObserver."""
        styler = ResponseStyler()
        js = styler.generate_injection_script()

        # Must check domains for safety
        assert "chatgpt.com" in js
        assert "perplexity.ai" in js

        # Must manage the specific style element ID
        assert STYLE_ELEMENT_ID in js
        assert "document.createElement('style')" in js

        # Must handle both initial load and dynamic streaming tokens
        assert "MutationObserver" in js
        assert "DOMContentLoaded" in js

    def test_cdp_command_parameters(self):
        """Verify parameters for Page.addScriptToEvaluateOnNewDocument and Runtime.evaluate."""
        styler = ResponseStyler()

        add_params = styler.get_cdp_add_script_params()
        assert "source" in add_params
        assert STYLE_ELEMENT_ID in add_params["source"]

        eval_params = styler.get_cdp_evaluate_params()
        assert "expression" in eval_params
        assert eval_params.get("returnByValue") is True
        assert STYLE_ELEMENT_ID in eval_params["expression"]


class TestResponseStylerIntegration:
    """Test suite for CDP integration with TabSession and CDPClient."""

    def test_tab_session_injects_styler_on_connection(self, qtbot):
        """Verify TabSession._on_connected registers Page and Runtime scripts."""
        with patch("PySide6.QtWebSockets.QWebSocket.open"):
            session = TabSession(target_id="tab-1", ws_url="ws://127.0.0.1:9222/tab-1")

        sent_commands = []

        def mock_send(method, params=None):
            sent_commands.append((method, params or {}))
            return 1

        session.send_command = mock_send
        session._on_connected()

        methods = [m[0] for m in sent_commands]
        assert "Network.enable" in methods
        assert "Page.enable" in methods
        assert "Runtime.enable" in methods
        assert "Fetch.enable" in methods
        assert "Page.addScriptToEvaluateOnNewDocument" in methods
        assert "Runtime.evaluate" in methods

        # Verify script contains style element ID
        add_cmd = next(c for c in sent_commands if c[0] == "Page.addScriptToEvaluateOnNewDocument")
        assert STYLE_ELEMENT_ID in add_cmd[1]["source"]

    def test_cdp_client_apply_response_styling(self, qtbot):
        """Verify CDPClient broadcasts response styling to all active tab sessions."""
        client = CDPClient(port=9222)
        mock_session_1 = MagicMock()
        mock_session_2 = MagicMock()

        client._active_sessions["tab-1"] = mock_session_1
        client._active_sessions["tab-2"] = mock_session_2

        client.apply_response_styling(color="#3B82F6")

        mock_session_1.inject_response_styler.assert_called_once_with(color="#3B82F6")
        mock_session_2.inject_response_styler.assert_called_once_with(color="#3B82F6")
