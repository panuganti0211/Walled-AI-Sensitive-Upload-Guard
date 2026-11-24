"""High-level browser controller orchestrating browser process and CDP lifecycle.

Coordinates BrowserManager, CDPClient, EnforcementManager, and DLP observation,
exposing a unified interface to the PySide6 desktop GUI.
"""

from typing import List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from app.browser.browser_manager import BrowserManager
from app.browser.cdp_client import CDPClient
from app.browser.enforcement_manager import EnforcementManager
from app.browser.models import ApprovalDecision, BrowserStatus, CandidateRequest, CDPStatus


class BrowserController(QObject):
    """High-level controller coordinating managed browser process, CDP, and DLP enforcement."""

    browser_status_changed = Signal(BrowserStatus)
    cdp_status_changed = Signal(CDPStatus)
    chatgpt_detected = Signal(bool)
    perplexity_detected = Signal(bool)
    candidate_observed = Signal(CandidateRequest)
    prompt_candidate_observed = Signal(CandidateRequest)
    upload_candidate_observed = Signal(CandidateRequest)

    # Enforcement signals
    approval_required = Signal(str, str, str, str, str, str)  # req_id, platform, type, target_name, reason, snippet
    request_continued = Signal(str, str, str)  # req_id, platform, type
    request_blocked = Signal(str, str, str)  # req_id, platform, type
    scan_error_occurred = Signal(str, str, str)  # req_id, platform, error_msg
    safe_file_authorized = Signal(str, str, str, str)  # file_id, platform, filename, file_type

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.browser_manager = BrowserManager()
        self.cdp_client = CDPClient(parent=self)

        # Initialize DLP Enforcement Manager with CDP continuation/blocking callbacks
        self.enforcement_manager = EnforcementManager(
            continue_fn=self.cdp_client.continue_request,
            fail_fn=self.cdp_client.fail_request,
            correlation_timeout=1.5,
            parent=self,
        )

        self._candidate_prompts_count = 0
        self._candidate_uploads_count = 0

        # Forward CDP client signals
        self.cdp_client.status_changed.connect(self.cdp_status_changed)
        self.cdp_client.chatgpt_detected.connect(self.chatgpt_detected)
        self.cdp_client.perplexity_detected.connect(self.perplexity_detected)
        self.cdp_client.candidate_observed.connect(self.candidate_observed)
        self.cdp_client.prompt_observed.connect(self._on_prompt_observed)
        self.cdp_client.upload_observed.connect(self._on_upload_observed)

        # Connect Fetch.requestPaused and DOM file bridge events to EnforcementManager
        self.cdp_client.request_paused.connect(self.enforcement_manager.handle_request_paused)
        self.cdp_client.file_captured.connect(self.enforcement_manager.handle_file_captured)

        # Forward enforcement manager signals to UI
        self.enforcement_manager.approval_required.connect(self.approval_required)
        self.enforcement_manager.request_continued.connect(self.request_continued)
        self.enforcement_manager.request_blocked.connect(self.request_blocked)
        self.enforcement_manager.scan_error_occurred.connect(self.scan_error_occurred)
        self.enforcement_manager.safe_file_authorized.connect(self.safe_file_authorized)

        # Healthcheck timer to verify browser process status
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(2000)
        self._health_timer.timeout.connect(self._check_browser_health)

    @property
    def candidate_prompts_count(self) -> int:
        return self._candidate_prompts_count

    @property
    def candidate_uploads_count(self) -> int:
        return self._candidate_uploads_count

    def launch(self, browser_key: str = "edge", urls: Optional[List[str]] = None) -> bool:
        """Launch managed browser and connect CDP observer."""
        self.browser_status_changed.emit(BrowserStatus.STARTING)
        success = self.browser_manager.launch_browser(browser_key=browser_key, urls=urls)

        if success and self.browser_manager.cdp_port:
            self.browser_status_changed.emit(BrowserStatus.RUNNING)
            # Begin CDP client target polling on the allocated port
            self.cdp_client.start(self.browser_manager.cdp_port)
            self._health_timer.start()
            return True
        else:
            self.browser_status_changed.emit(BrowserStatus.ERROR)
            return False

    def stop(self) -> None:
        """Stop the browser process and disconnect CDP."""
        self._health_timer.stop()
        self.enforcement_manager.cleanup_all()
        self.cdp_client.stop()
        self.browser_manager.stop_browser()
        self.browser_status_changed.emit(BrowserStatus.NOT_LAUNCHED)

    def resolve_approval(self, request_id: str, decision: ApprovalDecision) -> bool:
        """Forward user confirmation to the enforcement manager."""
        return self.enforcement_manager.resolve_request(request_id, decision)

    def set_ai_response_color(self, color: str) -> None:
        """Update AI response highlight color across all monitored browser tabs."""
        self.cdp_client.apply_response_styling(color=color)

    def _check_browser_health(self) -> None:
        """Periodically verify if the browser process is still alive."""
        if not self.browser_manager.is_running():
            self._health_timer.stop()
            self.enforcement_manager.cleanup_all()
            self.cdp_client.stop()
            self.browser_status_changed.emit(BrowserStatus.DISCONNECTED)

    def _on_prompt_observed(self, candidate: CandidateRequest) -> None:
        self._candidate_prompts_count += 1
        self.prompt_candidate_observed.emit(candidate)

    def _on_upload_observed(self, candidate: CandidateRequest) -> None:
        self._candidate_uploads_count += 1
        self.upload_candidate_observed.emit(candidate)
