"""Native desktop approval dialog for DLP sensitive content warnings.

Presents a secure, always-on-top confirmation dialog when WALLED_SENSITIVE
is detected in outgoing prompts or file uploads.
"""

from enum import Enum
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.browser.models import ApprovalDecision
from app.config.settings import config


class ApprovalDialog(QDialog):
    """Native always-on-top modal approval dialog for DLP enforcement."""

    # Signal emitted when a decision is confirmed
    decision_made = Signal(ApprovalDecision)

    def __init__(
        self,
        platform: str = "ChatGPT",
        content_type: str = "Prompt",
        file_name: Optional[str] = None,
        detection_reason: str = "WALLED_SENSITIVE marker detected",
        snippet: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.platform = platform
        self.content_type = content_type
        self.file_name = file_name
        self.detection_reason = detection_reason
        self.snippet = snippet

        # Safe default state: CANCEL
        self._decision = ApprovalDecision.CANCEL
        self._decision_emitted = False

        self._configure_window()
        self._init_ui()

    def _configure_window(self) -> None:
        """Configure modal behavior and always-on-top window flags."""
        is_unverifiable = (
            "unverifiable" in self.detection_reason.lower()
            or "fail-secure" in self.detection_reason.lower()
        )
        if is_unverifiable:
            self.setWindowTitle(f"Unverifiable Upload Alert — {config.app_name}")
        else:
            self.setWindowTitle(f"Security Alert — {config.app_name}")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setMaximumWidth(600)

        # Ensure dialog stays above the monitored browser window
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
        )

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # Header with Alert Banner
        header_frame = QFrame()
        header_frame.setStyleSheet(
            "QFrame { background-color: #FEF2F2; border: 1px solid #FECACA; "
            "border-radius: 8px; padding: 14px; }"
        )
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(8, 8, 8, 8)
        header_layout.setSpacing(12)

        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size: 26px;")
        header_layout.addWidget(icon_label)

        title_col = QVBoxLayout()
        is_unverifiable = (
            "unverifiable" in self.detection_reason.lower()
            or "fail-secure" in self.detection_reason.lower()
        )
        if is_unverifiable:
            alert_title = QLabel("Unverifiable Upload (Fail-Secure Policy)")
            alert_subtitle = QLabel(
                "Inspection of file stream bytes was unavailable at browser boundary. "
                "Transmission was paused under Fail-Secure DLP policy."
            )
        else:
            alert_title = QLabel("Sensitive Content Detected")
            alert_subtitle = QLabel(
                "Outgoing transmission was paused by DLP protection before sending."
            )
        alert_title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        alert_title.setStyleSheet("color: #991B1B;")
        alert_subtitle.setStyleSheet("color: #7F1D1D; font-size: 11px;")
        title_col.addWidget(alert_title)
        title_col.addWidget(alert_subtitle)
        header_layout.addLayout(title_col, stretch=1)
        layout.addWidget(header_frame)

        # Content Details Section
        details_frame = QFrame()
        details_frame.setStyleSheet(
            "QFrame { background-color: #F8FAFC; border: 1px solid #E2E8F0; "
            "border-radius: 8px; padding: 14px; }"
        )
        details_layout = QVBoxLayout(details_frame)
        details_layout.setSpacing(10)

        details_layout.addWidget(self._create_detail_row("Target Application:", self.platform))
        details_layout.addWidget(self._create_detail_row("Content Type:", self.content_type))

        display_filename = self.file_name
        if not display_filename or display_filename == "Attached File":
            if is_unverifiable:
                display_filename = "Unidentified Attachment (Stream Inaccessible)"
            else:
                display_filename = "Attached File"

        if "file" in self.content_type.lower() or self.file_name:
            details_layout.addWidget(self._create_detail_row("File Name:", display_filename))

        details_layout.addWidget(self._create_detail_row("Detection Reason:", self.detection_reason))

        layout.addWidget(details_frame)

        # Guidance Note
        note_label = QLabel(
            "• <b>Cancel (Safe Default)</b>: Blocks transmission. Content remains editable.<br>"
            "• <b>Continue</b>: Authorizes transmission without modifications."
        )
        note_label.setStyleSheet("color: #475569; font-size: 11px; line-height: 1.4;")
        layout.addWidget(note_label)

        # Action Buttons Row
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.addStretch()

        # Continue Button (Subtle, secondary warning)
        self.btn_continue = QPushButton("Continue")
        self.btn_continue.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; color: #DC2626; border: 1px solid #DC2626; "
            "padding: 9px 18px; border-radius: 6px; font-weight: 600; font-size: 12px; }"
            "QPushButton:hover { background-color: #FEF2F2; }"
        )
        self.btn_continue.setAutoDefault(False)
        self.btn_continue.setDefault(False)
        self.btn_continue.clicked.connect(self._on_continue)
        button_layout.addWidget(self.btn_continue)

        # Cancel Button (Highlighted safe default)
        self.btn_cancel = QPushButton("Cancel Transmission")
        self.btn_cancel.setStyleSheet(
            "QPushButton { background-color: #0F172A; color: #FFFFFF; border: none; "
            "padding: 9px 20px; border-radius: 6px; font-weight: bold; font-size: 12px; }"
            "QPushButton:hover { background-color: #1E293B; }"
            "QPushButton:focus { outline: 2px solid #2563EB; }"
        )
        self.btn_cancel.setAutoDefault(True)
        self.btn_cancel.setDefault(True)
        self.btn_cancel.clicked.connect(self._on_cancel)
        button_layout.addWidget(self.btn_cancel)

        layout.addLayout(button_layout)

        # Focus Cancel button by default
        self.btn_cancel.setFocus()

    def _create_detail_row(self, label: str, value: str) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: #64748B; font-weight: 600; font-size: 12px; min-width: 140px;")
        val = QLabel(value)
        val.setStyleSheet("color: #0F172A; font-weight: bold; font-size: 12px;")

        row_layout.addWidget(lbl)
        row_layout.addWidget(val, stretch=1)
        return row

    @property
    def decision(self) -> ApprovalDecision:
        """Return the user's decision."""
        return self._decision

    def _on_continue(self) -> None:
        """Handle Continue button click."""
        if not self._decision_emitted:
            self._decision_emitted = True
            self._decision = ApprovalDecision.CONTINUE
            self.decision_made.emit(self._decision)
        self.accept()

    def _on_cancel(self) -> None:
        """Handle Cancel button click."""
        if not self._decision_emitted:
            self._decision_emitted = True
            self._decision = ApprovalDecision.CANCEL
            self.decision_made.emit(self._decision)
        self.reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Window close (X button) must always behave safely as Cancel."""
        if not self._decision_emitted:
            self._decision_emitted = True
            self._decision = ApprovalDecision.CANCEL
            self.decision_made.emit(self._decision)
        event.accept()

    def keyPressEvent(self, event) -> None:
        """Keyboard Escape must trigger Cancel safely."""
        if event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
        else:
            super().keyPressEvent(event)

    @classmethod
    def request_approval(
        cls,
        parent: Optional[QWidget] = None,
        platform: str = "ChatGPT",
        content_type: str = "Prompt",
        file_name: Optional[str] = None,
        detection_reason: str = "WALLED_SENSITIVE marker detected",
        snippet: Optional[str] = None,
    ) -> ApprovalDecision:
        """Convenience method to show the modal dialog and return the decision."""
        dialog = cls(
            platform=platform,
            content_type=content_type,
            file_name=file_name,
            detection_reason=detection_reason,
            snippet=snippet,
            parent=parent,
        )
        dialog.exec()
        return dialog.decision
