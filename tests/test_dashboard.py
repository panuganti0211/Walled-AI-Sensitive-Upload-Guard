"""Unit and UI tests for the desktop dashboard window."""

import pytest
from PySide6.QtCore import Qt

from app.browser.models import BrowserStatus, CandidateRequest, CDPStatus
from app.desktop.approval_dialog import ApprovalDecision
from app.desktop.main_window import MainWindow


class TestDashboard:
    """Test suite for MainWindow DLP dashboard and audit integration."""

    @pytest.fixture
    def window(self, qtbot):
        win = MainWindow()
        qtbot.addWidget(win)
        return win

    def test_dashboard_initialization(self, window):
        """Verify dashboard title, layout, and initial state."""
        assert "Walled AI Sensitive Upload Guard" in window.windowTitle()
        assert window.card_protection is not None
        assert window.card_chatgpt is not None
        assert window.card_perplexity is not None
        assert window.card_detections is not None
        assert window.btn_launch_edge is not None
        assert window.btn_launch_chrome is not None
        assert window.btn_stop_browser is not None

    def test_monitoring_statuses_accurately_report_not_connected(self, window):
        """Verify status cards do NOT falsely claim monitoring is active."""
        chatgpt_status = window.card_chatgpt.lbl_val.text()
        perplexity_status = window.card_perplexity.lbl_val.text()

        # Both must explicitly report Not Connected until Phase 4
        assert "Not Connected" in chatgpt_status
        assert "Not Connected" in perplexity_status

    def test_counter_widgets_initialization(self, window):
        """Verify initial counters are all zero."""
        assert window.prompts_blocked == 0
        assert window.prompts_allowed == 0
        assert window.files_blocked == 0
        assert window.files_allowed == 0
        assert window.total_detections == 0
        assert window.observed_prompts == 0
        assert window.observed_uploads == 0
        assert window.sensitive_prompts_detected == 0
        assert window.sensitive_uploads_detected == 0
        assert window.unverifiable_uploads == 0

        assert window.card_prompts_blocked.val_label.text() == "0"
        assert window.card_prompts_allowed.val_label.text() == "0"
        assert window.card_files_blocked.val_label.text() == "0"
        assert window.card_files_allowed.val_label.text() == "0"
        assert window.card_observed_prompts.val_label.text() == "0"
        assert window.card_observed_uploads.val_label.text() == "0"
        assert window.card_sensitive_prompts.val_label.text() == "0"
        assert window.card_sensitive_uploads.val_label.text() == "0"
        assert window.card_unverifiable_uploads.val_label.text() == "0"

    def test_record_decision_updates_counters(self, window):
        """Verify record_decision updates appropriate counters and labels."""
        # 1. Block a prompt
        window.record_decision("ChatGPT", "Prompt", ApprovalDecision.CANCEL)
        assert window.prompts_blocked == 1
        assert window.prompts_allowed == 0
        assert window.total_detections == 1
        assert window.card_prompts_blocked.val_label.text() == "1"

        # 2. Allow a prompt
        window.record_decision("ChatGPT", "Prompt", ApprovalDecision.CONTINUE)
        assert window.prompts_blocked == 1
        assert window.prompts_allowed == 1
        assert window.total_detections == 2
        assert window.card_prompts_allowed.val_label.text() == "1"

        # 3. Block a file upload
        window.record_decision("Perplexity", "File Upload (PDF)", ApprovalDecision.CANCEL, target_name="secret.pdf")
        assert window.files_blocked == 1
        assert window.files_allowed == 0
        assert window.total_detections == 3
        assert window.card_files_blocked.val_label.text() == "1"

        # 4. Allow a file upload
        window.record_decision("Perplexity", "File Upload (TXT)", ApprovalDecision.CONTINUE, target_name="safe.txt")
        assert window.files_allowed == 1
        assert window.total_detections == 4
        assert window.card_files_allowed.val_label.text() == "1"

    def test_audit_table_initialization_and_rows(self, window):
        """Verify audit log table structure and real-time row insertion."""
        assert window.audit_table.columnCount() == 6
        assert window.audit_table.rowCount() == 0

        # Record an event
        entry = window.record_decision(
            platform="ChatGPT",
            content_type="Prompt",
            decision=ApprovalDecision.CANCEL,
            target_name="Test prompt content",
        )

        assert window.audit_table.rowCount() == 1
        assert window.audit_table.item(0, 1).text() == "ChatGPT"
        assert window.audit_table.item(0, 2).text() == "Prompt"
        assert "Blocked" in window.audit_table.item(0, 5).text()

    def test_browser_and_cdp_status_slots(self, window):
        """Verify UI slots update browser runtime and CDP status labels accurately."""
        # Simulate browser running
        window._on_browser_status_changed(BrowserStatus.RUNNING)
        assert "Running" in window.lbl_browser_runtime_status.text()
        assert window.btn_stop_browser.isEnabled() is True
        assert window.btn_launch_edge.isEnabled() is False

        # Simulate CDP connected
        window._on_cdp_status_changed(CDPStatus.CONNECTED)
        assert "Connected" in window.lbl_cdp_indicator.text()

        # Simulate ChatGPT detected
        window._on_chatgpt_detected(True)
        assert "Detected" in window.card_chatgpt.lbl_val.text()

        # Simulate Perplexity detected
        window._on_perplexity_detected(True)
        assert "Detected" in window.card_perplexity.lbl_val.text()

        # Simulate candidate observations
        sample_prompt = CandidateRequest(
            request_id="r1",
            platform="ChatGPT",
            request_type="prompt",
            method="POST",
            url="https://chatgpt.com/backend-api/conversation",
            path="/backend-api/conversation",
            timestamp="2026-11-22 10:00:00",
        )
        sample_upload = CandidateRequest(
            request_id="r2",
            platform="Perplexity",
            request_type="upload",
            method="POST",
            url="https://www.perplexity.ai/api/upload",
            path="/api/upload",
            timestamp="2026-11-22 10:00:01",
        )

        window._on_candidate_prompt_observed(sample_prompt)
        window._on_candidate_upload_observed(sample_upload)

        assert window.observed_prompts == 1
        assert window.observed_uploads == 1
        assert window.card_observed_prompts.val_label.text() == "1"
        assert window.card_observed_uploads.val_label.text() == "1"

    def test_distinguish_marker_detected_from_unverifiable_upload(self, window):
        """Verify dashboard strictly separates actual marker detections from unverifiable uploads."""
        # 1. Simulate an unverifiable file stream (Fail-Secure Policy)
        window.record_decision(
            platform="ChatGPT",
            content_type="File Upload (TXT)",
            decision=ApprovalDecision.CANCEL,
            target_name="test.txt",
            detection_reason="Unverifiable file stream (Fail-Secure Policy)",
        )

        assert window.unverifiable_uploads == 1
        assert window.card_unverifiable_uploads.val_label.text() == "1"
        # Sensitive uploads MUST NOT increment for unverifiable stream
        assert window.sensitive_uploads_detected == 0
        assert window.card_sensitive_uploads.val_label.text() == "0"
        assert window.files_blocked == 1
        assert window.card_files_blocked.val_label.text() == "1"

        # Verify audit table row details
        assert window.audit_table.rowCount() == 1
        assert window.audit_table.item(0, 1).text() == "ChatGPT"
        assert window.audit_table.item(0, 2).text() == "File Upload (TXT)"
        assert window.audit_table.item(0, 3).text() == "test.txt"
        assert "Unverifiable" in window.audit_table.item(0, 4).text()
        assert "Blocked" in window.audit_table.item(0, 5).text()

        # 2. Simulate an actual sensitive marker detection
        window.record_decision(
            platform="ChatGPT",
            content_type="File Upload (TXT)",
            decision=ApprovalDecision.CANCEL,
            target_name="secret.txt",
            detection_reason="WALLED_SENSITIVE marker detected in secret.txt",
        )

        # Now sensitive uploads increments to 1, while unverifiable remains 1
        assert window.sensitive_uploads_detected == 1
        assert window.card_sensitive_uploads.val_label.text() == "1"
        assert window.unverifiable_uploads == 1
        assert window.card_unverifiable_uploads.val_label.text() == "1"
        assert window.files_blocked == 2
        assert window.card_files_blocked.val_label.text() == "2"

        # Verify second audit table row
        assert window.audit_table.rowCount() == 2
        assert window.audit_table.item(1, 3).text() == "secret.txt"
        assert "WALLED_SENSITIVE" in window.audit_table.item(1, 4).text()
