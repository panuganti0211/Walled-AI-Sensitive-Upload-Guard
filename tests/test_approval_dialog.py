"""Unit and UI tests for the native desktop ApprovalDialog."""

import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QKeyEvent, QCloseEvent

from app.desktop.approval_dialog import ApprovalDecision, ApprovalDialog


class TestApprovalDialog:
    """Test suite for the native DLP ApprovalDialog."""

    def test_dialog_construction(self, qtbot):
        """Verify modal dialog construction and metadata rendering."""
        dialog = ApprovalDialog(
            platform="ChatGPT",
            content_type="Prompt",
            file_name=None,
            detection_reason="WALLED_SENSITIVE found in prompt text",
        )
        qtbot.addWidget(dialog)

        assert "Security Alert" in dialog.windowTitle()
        assert dialog.platform == "ChatGPT"
        assert dialog.content_type == "Prompt"
        assert dialog.file_name is None
        assert dialog.decision == ApprovalDecision.CANCEL

    def test_always_on_top_and_modal_flags(self, qtbot):
        """Verify dialog stays above browser windows and is application modal."""
        dialog = ApprovalDialog(platform="Perplexity", content_type="File Upload")
        qtbot.addWidget(dialog)

        flags = dialog.windowFlags()
        assert bool(flags & Qt.WindowType.WindowStaysOnTopHint) is True
        assert dialog.isModal() is True

    def test_cancel_is_default_and_focused(self, qtbot):
        """Verify Cancel is the safe default action and Continue is not auto-default."""
        dialog = ApprovalDialog()
        qtbot.addWidget(dialog)

        assert dialog.btn_cancel.isDefault() is True
        assert dialog.btn_continue.isDefault() is False
        assert dialog.btn_continue.autoDefault() is False
        assert dialog.decision == ApprovalDecision.CANCEL

    def test_continue_decision_action(self, qtbot):
        """Verify clicking Continue sets decision to CONTINUE and emits signal."""
        dialog = ApprovalDialog()
        qtbot.addWidget(dialog)

        with qtbot.waitSignal(dialog.decision_made, timeout=1000) as blocker:
            qtbot.mouseClick(dialog.btn_continue, Qt.MouseButton.LeftButton)

        assert dialog.decision == ApprovalDecision.CONTINUE
        assert blocker.args == [ApprovalDecision.CONTINUE]

    def test_cancel_decision_action(self, qtbot):
        """Verify clicking Cancel sets decision to CANCEL and emits signal."""
        dialog = ApprovalDialog()
        qtbot.addWidget(dialog)

        with qtbot.waitSignal(dialog.decision_made, timeout=1000) as blocker:
            qtbot.mouseClick(dialog.btn_cancel, Qt.MouseButton.LeftButton)

        assert dialog.decision == ApprovalDecision.CANCEL
        assert blocker.args == [ApprovalDecision.CANCEL]

    def test_escape_key_defaults_to_cancel(self, qtbot):
        """Verify pressing Escape key triggers Cancel safely."""
        dialog = ApprovalDialog()
        qtbot.addWidget(dialog)

        with qtbot.waitSignal(dialog.decision_made, timeout=1000) as blocker:
            qtbot.keyClick(dialog, Qt.Key.Key_Escape)

        assert dialog.decision == ApprovalDecision.CANCEL
        assert blocker.args == [ApprovalDecision.CANCEL]

    def test_close_event_defaults_to_cancel(self, qtbot):
        """Verify closing dialog via window 'X' button treats action as Cancel."""
        dialog = ApprovalDialog()
        qtbot.addWidget(dialog)

        with qtbot.waitSignal(dialog.decision_made, timeout=1000) as blocker:
            close_evt = QCloseEvent()
            dialog.closeEvent(close_evt)

        assert dialog.decision == ApprovalDecision.CANCEL
        assert blocker.args == [ApprovalDecision.CANCEL]

    def test_file_upload_dialog_metadata(self, qtbot):
        """Verify file upload metadata (filename and type) are displayed."""
        dialog = ApprovalDialog(
            platform="ChatGPT",
            content_type="File Upload (PDF)",
            file_name="quarterly_report.pdf",
            detection_reason="WALLED_SENSITIVE found on page 2",
        )
        qtbot.addWidget(dialog)

        assert dialog.file_name == "quarterly_report.pdf"
        assert dialog.content_type == "File Upload (PDF)"
