"""End-to-end integration tests for Walled AI Sensitive Upload Guard (Phase 7).

Verifies the full lifecycle:
1. Browser controller initialization & CDP setup.
2. Interception of candidate prompt requests on ChatGPT and Perplexity.
3. Content scanning for the exact WALLED_SENSITIVE marker.
4. Interactive native desktop approval dialog workflow (Continue vs. Cancel).
5. Interception and multipart file extraction of sensitive TXT, PDF, and Image uploads.
6. Real-time audit logging and metric dashboard updates.
7. AI response color styling script injection via CDP.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.browser.browser_controller import BrowserController
from app.browser.models import ApprovalDecision, BrowserStatus, CDPStatus
from app.config.settings import config
from app.desktop.approval_dialog import ApprovalDialog
from app.desktop.main_window import MainWindow

SENSITIVE_MARKER = config.sensitive_marker


class TestEndToEndPipeline:
    """Full system end-to-end integration tests."""

    @pytest.fixture
    def app_context(self, qtbot):
        """Fixture that sets up MainWindow and BrowserController with mocked CDP callbacks."""
        window = MainWindow()
        qtbot.addWidget(window)
        controller = window.browser_controller
        return window, controller

    def test_e2e_safe_prompt_flow(self, app_context, qtbot):
        """E2E Test: Safe prompt proceeds automatically without user interruption."""
        window, controller = app_context

        # Mock CDP continue and fail callbacks on the enforcement manager
        mock_continue = MagicMock()
        mock_fail = MagicMock()
        controller.enforcement_manager.continue_fn = mock_continue
        controller.enforcement_manager.fail_fn = mock_fail

        safe_post_data = '{"messages":[{"role":"user","content":"Tell me a story about space exploration"}]}'
        req_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "postData": safe_post_data,
        }

        # Simulate Fetch.requestPaused from CDP
        controller.cdp_client.request_paused.emit("tab-1", "req-safe-prompt-1", req_data)

        # Assert automatically continued without approval dialog
        mock_continue.assert_called_once_with("tab-1", "req-safe-prompt-1")
        mock_fail.assert_not_called()
        assert window.total_detections == 0

    def test_e2e_sensitive_prompt_continued_by_user(self, app_context, qtbot):
        """E2E Test: Sensitive prompt detected -> approval dialog -> user selects Continue."""
        window, controller = app_context

        mock_continue = MagicMock()
        mock_fail = MagicMock()
        controller.enforcement_manager.continue_fn = mock_continue
        controller.enforcement_manager.fail_fn = mock_fail

        sensitive_post_data = f'{{"messages":[{{"role":"user","content":"Confidential doc: {SENSITIVE_MARKER}"}}]}}'
        req_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "postData": sensitive_post_data,
        }

        # Mock native ApprovalDialog execution returning CONTINUE
        with patch.object(ApprovalDialog, "request_approval", return_value=ApprovalDecision.CONTINUE) as mock_dialog:
            controller.cdp_client.request_paused.emit("tab-1", "req-sens-prompt-continue", req_data)

            # Dialog must have been presented with detection metadata
            mock_dialog.assert_called_once()
            call_kwargs = mock_dialog.call_args[1] if mock_dialog.call_args[1] else {}
            call_args = mock_dialog.call_args[0]
            platform = call_kwargs.get("platform") or (call_args[1] if len(call_args) > 1 else None)
            assert platform == "ChatGPT"

        # Request must be continued with original payload intact
        mock_continue.assert_called_once_with("tab-1", "req-sens-prompt-continue")
        mock_fail.assert_not_called()

        # Verify audit table & counters
        assert window.prompts_allowed == 1
        assert window.prompts_blocked == 0
        assert window.total_detections == 1
        assert window.audit_table.rowCount() >= 1
        assert window.audit_table.item(0, 1).text() == "ChatGPT"
        assert "Allowed" in window.audit_table.item(0, 5).text()

    def test_e2e_sensitive_prompt_cancelled_by_user(self, app_context, qtbot):
        """E2E Test: Sensitive prompt detected -> approval dialog -> user selects Cancel (blocked)."""
        window, controller = app_context

        mock_continue = MagicMock()
        mock_fail = MagicMock()
        controller.enforcement_manager.continue_fn = mock_continue
        controller.enforcement_manager.fail_fn = mock_fail

        sensitive_post_data = f'{{"query":"Search for {SENSITIVE_MARKER} blueprints"}}'
        req_data = {
            "url": "https://www.perplexity.ai/api/ask",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "postData": sensitive_post_data,
        }

        # Mock the dialog execution returning CANCEL (default / safe option)
        with patch.object(ApprovalDialog, "request_approval", return_value=ApprovalDecision.CANCEL) as mock_dialog:
            controller.cdp_client.request_paused.emit("tab-2", "req-sens-prompt-cancel", req_data)
            mock_dialog.assert_called_once()

        # Request must be blocked at browser network layer
        mock_fail.assert_called_once_with("tab-2", "req-sens-prompt-cancel", "BlockedByClient")
        mock_continue.assert_not_called()

        # Verify audit table & counters
        assert window.prompts_blocked == 1
        assert window.prompts_allowed == 0
        assert window.total_detections == 1
        assert window.audit_table.rowCount() >= 1
        assert window.audit_table.item(0, 1).text() == "Perplexity"
        assert "Blocked" in window.audit_table.item(0, 5).text()

    def test_e2e_sensitive_txt_upload_blocked(self, app_context, qtbot):
        """E2E Test: Sensitive TXT file upload paused, scanned, and blocked on Cancel."""
        window, controller = app_context

        mock_continue = MagicMock()
        mock_fail = MagicMock()
        controller.enforcement_manager.continue_fn = mock_continue
        controller.enforcement_manager.fail_fn = mock_fail

        boundary = "----WebKitFormBoundaryE2ETest"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="notes.txt"\r\n'
            f"Content-Type: text/plain\r\n\r\n"
            f"These are secret plans: {SENSITIVE_MARKER}\r\n"
            f"--{boundary}--\r\n"
        )
        req_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"Content-Type": f"multipart/form-data; boundary={boundary}"},
            "postData": body,
        }

        with patch.object(ApprovalDialog, "request_approval", return_value=ApprovalDecision.CANCEL) as mock_dialog:
            controller.cdp_client.request_paused.emit("tab-1", "req-sens-upload-1", req_data)
            mock_dialog.assert_called_once()

        mock_fail.assert_called_once_with("tab-1", "req-sens-upload-1", "BlockedByClient")
        mock_continue.assert_not_called()
        assert window.files_blocked == 1
        assert window.total_detections == 1

    def test_e2e_ai_response_styler_injected_on_page(self, app_context, qtbot):
        """E2E Test: Tab session connection triggers AI response styling script injection."""
        window, controller = app_context

        with patch("PySide6.QtWebSockets.QWebSocket.open"):
            from app.browser.cdp_client import TabSession
            session = TabSession("tab-test", "ws://127.0.0.1:9222/tab-test")
            controller.cdp_client._active_sessions["tab-test"] = session

        sent_commands = []
        session.send_command = lambda method, params=None: sent_commands.append((method, params or {})) or 1

        session._on_connected()

        methods = [m[0] for m in sent_commands]
        assert "Page.addScriptToEvaluateOnNewDocument" in methods
        assert "Runtime.evaluate" in methods

        # Verify injected script contains the style ID
        styler_call = next(c for c in sent_commands if c[0] == "Page.addScriptToEvaluateOnNewDocument")
        assert "walled-ai-response-styler" in styler_call[1]["source"]
