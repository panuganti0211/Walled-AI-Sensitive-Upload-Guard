"""DLP enforcement engine managing paused request lifecycle and approval resolution.

Coordinates synchronous request holding, content inspection, and terminal resolution
(Continue vs. Cancel/Block) over Chrome DevTools Protocol Fetch domain.
Integrates with the DOM FileBridge to inspect actual file bytes (TXT, PDF, and Images)
before transmission, preventing race conditions and ensuring fail-secure policy enforcement.
"""

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, QTimer, Signal

from app.browser.models import ApprovalDecision, CandidateRequest
from app.browser.payload_extractor import UploadedPart, extract_multipart_files, extract_prompt_strings
from app.browser.request_classifier import classify_request
from app.scanner.models import ScanResult
from app.scanner.pdf_scanner import PDFScanner
from app.scanner.text_scanner import TextScanner
from app.scanner.unified_scanner import UnifiedScanner, default_unified_scanner
from app.security.diagnostic_logger import diag_logger


class RequestLifecycleState(str, Enum):
    """Lifecycle state of a paused network request."""

    PAUSED = "paused"
    SCANNING = "scanning"
    AWAITING_DECISION = "awaiting_decision"
    RESOLVED = "resolved"


@dataclass
class PausedRequest:
    """State tracking for a paused request held in Chromium CDP."""

    request_id: str
    target_id: str
    platform: str
    content_type: str
    target_name: Optional[str]
    url: str
    created_at: float
    state: RequestLifecycleState = RequestLifecycleState.PAUSED
    resolved: bool = False
    decision: Optional[ApprovalDecision] = None
    timeout_timer: Optional[QTimer] = None


@dataclass
class BridgeFile:
    """Represents a file captured at the DOM level and passed to Python for scanning."""

    file_id: str
    target_id: str
    filename: str
    size: int
    mime_type: str
    last_modified: int
    content_bytes: bytes
    sha256: str
    received_at: float
    scan_result: Optional[ScanResult] = None
    is_sensitive: bool = False
    decision: Optional[ApprovalDecision] = None
    timeout_timer: Optional[QTimer] = None
    pending_request_ids: Set[str] = field(default_factory=set)
    recorded_in_audit: bool = False

    @property
    def file_type(self) -> str:
        if "." in self.filename:
            return self.filename.split(".")[-1].upper()
        return "File"


@dataclass
class PendingUpload:
    """A paused upload request waiting for DOM file bridge correlation."""

    request_id: str
    target_id: str
    req_state: PausedRequest
    inferred_filename: Optional[str]
    inferred_size: Optional[int]
    created_at: float
    grace_timer: Optional[QTimer] = None


class EnforcementManager(QObject):
    """Enforces DLP policies on paused CDP requests and captured DOM file streams."""

    # Signals emitted to UI
    approval_required = Signal(str, str, str, str, str, str)  # req_id/file_id, platform, type, target_name, reason, snippet
    request_continued = Signal(str, str, str)  # req_id, platform, type
    request_blocked = Signal(str, str, str)  # req_id, platform, type
    scan_error_occurred = Signal(str, str, str)  # req_id, platform, error_msg
    safe_file_authorized = Signal(str, str, str, str)  # file_id, platform, filename, file_type

    def __init__(
        self,
        continue_fn: Callable[[str, str], None],
        fail_fn: Callable[[str, str, str], None],
        scanner: Optional[UnifiedScanner] = None,
        timeout_seconds: float = 60.0,
        correlation_timeout: float = 0.4,
        parent: Optional[QObject] = None,
    ):
        """Initialize EnforcementManager.

        Args:
            continue_fn: Callback (target_id, request_id) -> sends Fetch.continueRequest.
            fail_fn: Callback (target_id, request_id, reason) -> sends Fetch.failRequest.
            scanner: UnifiedScanner instance for inspecting prompts and files.
            timeout_seconds: Maximum time to await user decision before fail-secure auto-block.
            correlation_timeout: Seconds to hold an upload network request waiting for DOM bridge file event.
        """
        super().__init__(parent)
        self.continue_fn = continue_fn
        self.fail_fn = fail_fn
        self.scanner = scanner or default_unified_scanner
        self.text_scanner = TextScanner()
        self.pdf_scanner = PDFScanner()
        self.timeout_seconds = timeout_seconds
        self.correlation_timeout = correlation_timeout

        # Active paused requests: {request_id: PausedRequest}
        self._paused_requests: Dict[str, PausedRequest] = {}

        # Files captured from DOM bridge: {file_id: BridgeFile}
        self._bridge_files: Dict[str, BridgeFile] = {}

        # Upload requests waiting for bridge correlation: {request_id: PendingUpload}
        self._pending_uploads: Dict[str, PendingUpload] = {}

        # Platform memory per tab target: {target_id: platform}
        self._target_platforms: Dict[str, str] = {}

    def handle_request_paused(self, target_id: str, request_id: str, request_data: dict) -> None:
        """Process an incoming Fetch.requestPaused event from Chromium."""
        if not request_id or request_id in self._paused_requests:
            return

        url = request_data.get("url", "")
        method = request_data.get("method", "GET")
        headers = request_data.get("headers", {})
        post_data = request_data.get("postData")
        has_post_data = request_data.get("hasPostData", False)

        candidate = classify_request(
            url=url,
            method=method,
            headers=headers,
            has_post_data=has_post_data or bool(post_data),
            request_id=request_id,
        )

        # Update platform tracking for this tab
        if candidate.platform != "Unknown":
            self._target_platforms[target_id] = candidate.platform
        elif target_id in self._target_platforms:
            candidate.platform = self._target_platforms[target_id]
        elif candidate.is_candidate_upload:
            candidate.platform = (
                next(iter(self._target_platforms.values()))
                if self._target_platforms
                else "Cloud Storage"
            )

        # 1. Non-candidate requests (static assets, navigation, unrelated GETs) -> Auto-continue
        if candidate.request_type in ("other", "navigation"):
            self._immediate_continue(target_id, request_id)
            return

        # 2. Non-upload requests on unknown platforms -> Auto-continue
        if candidate.platform == "Unknown" and not candidate.is_candidate_upload:
            self._immediate_continue(target_id, request_id)
            return

        # 2. Register paused request state
        req_state = PausedRequest(
            request_id=request_id,
            target_id=target_id,
            platform=candidate.platform,
            content_type="Prompt" if candidate.is_candidate_prompt else "File Upload",
            target_name=None,
            url=url,
            created_at=time.time(),
            state=RequestLifecycleState.SCANNING,
        )
        self._paused_requests[request_id] = req_state

        # 3. Route to specific inspector
        if candidate.is_candidate_prompt:
            self._inspect_prompt(req_state, post_data)
        elif candidate.is_candidate_upload:
            self._inspect_upload(req_state, post_data, headers)
        elif candidate.is_candidate_upload_init:
            self._inspect_upload_init(req_state, post_data, headers)
        else:
            self._immediate_continue(target_id, request_id)

    def handle_file_captured(self, target_id: str, file_data: dict) -> None:
        """Handle file bytes intercepted by the DOM file bridge and scan contents."""
        file_id = file_data.get("file_id") or f"fb_{int(time.time()*1000)}"
        if file_id in self._bridge_files:
            diag_logger.debug("[Bridge Duplicate] Ignoring duplicate delivery for file_id=%s", file_id)
            return

        filename = file_data.get("name") or "unnamed_upload"
        size = file_data.get("size") or 0
        mime_type = file_data.get("type") or ""
        last_modified = file_data.get("last_modified") or 0
        oversized = file_data.get("oversized", False)
        base64_data = file_data.get("base64") or ""

        diag_logger.info(
            "[Bridge File Received] target=%s file_id=%s filename='%s' size=%d mime='%s'",
            target_id,
            file_id,
            filename,
            size,
            mime_type,
        )

        # Decode raw file bytes safely
        content_bytes = b""
        if base64_data:
            try:
                content_bytes = base64.b64decode(base64_data)
            except Exception as e:
                diag_logger.error("[Bridge Decode Error] Failed base64 decode for %s: %s", filename, e)
                oversized = True

        diag_logger.info(
            "[STAGE: Payload decoded successfully] file_id=%s filename='%s' size=%d bytes mime='%s' oversized=%s",
            file_id,
            filename,
            len(content_bytes),
            mime_type,
            oversized,
        )

        sha256_hash = hashlib.sha256(content_bytes).hexdigest() if content_bytes else ""
        bridge_file = BridgeFile(
            file_id=file_id,
            target_id=target_id,
            filename=filename,
            size=size,
            mime_type=mime_type,
            last_modified=last_modified,
            content_bytes=content_bytes,
            sha256=sha256_hash,
            received_at=time.time(),
        )

        platform = self._target_platforms.get(target_id, "ChatGPT")

        diag_logger.info(
            "[STAGE: Scanner invoked] file='%s' size=%d bytes",
            filename,
            len(content_bytes),
        )

        # Scan the actual file bytes using the unified scanner (TXT, PDF, Image OCR)
        if oversized:
            scan_result = ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=filename,
                error="File exceeds maximum in-memory inspection size (Fail-Secure Policy)",
            )
        else:
            scan_result = self.scanner.scan_bytes(content_bytes, filename)

        bridge_file.scan_result = scan_result
        bridge_file.is_sensitive = scan_result.is_sensitive

        diag_logger.info(
            "[STAGE: Scanner result] file='%s' is_sensitive=%s successful=%s error='%s' locations=%s",
            filename,
            scan_result.is_sensitive,
            scan_result.scan_successful,
            scan_result.error or "",
            scan_result.locations,
        )

        if bridge_file.is_sensitive:
            # Sensitive marker detected -> Prompt user with native approval dialog
            reason = f"WALLED_SENSITIVE marker detected in {filename}"
            if scan_result.locations:
                loc_str = ", ".join(str(l) for l in scan_result.locations)
                reason += f" (Location: {loc_str})"
            snippet = scan_result.extracted_text[:250] if scan_result.extracted_text else ""
            self._start_bridge_timeout(bridge_file)
            diag_logger.info(
                "[Enforcement Alert] WALLED_SENSITIVE detected in upload: '%s'. Presenting native dialog.",
                filename,
            )
            self.approval_required.emit(
                bridge_file.file_id,
                platform,
                f"File Upload ({bridge_file.file_type})",
                filename,
                reason,
                snippet,
            )
        elif not scan_result.scan_successful:
            # Scanner error / unsupported format -> Fail-secure approval dialog
            reason = f"File scan error on {filename}: {scan_result.error}"
            self.scan_error_occurred.emit(bridge_file.file_id, platform, scan_result.error or "")
            self._start_bridge_timeout(bridge_file)
            diag_logger.warning(
                "[Enforcement Alert] Scan error on upload: '%s' (%s). Presenting fail-secure dialog.",
                filename,
                scan_result.error,
            )
            self.approval_required.emit(
                bridge_file.file_id,
                platform,
                f"File Upload ({bridge_file.file_type})",
                filename,
                reason,
                "",
            )
        else:
            # Safe file -> auto-authorized to transmit
            diag_logger.info("[Enforcement] File '%s' verified safe. Auto-authorizing transmission.", filename)
            bridge_file.decision = ApprovalDecision.CONTINUE

        self._bridge_files[file_id] = bridge_file

        # Resolve any network requests that arrived while this file was scanning
        self._match_pending_uploads_for_file(bridge_file)

    def _inspect_prompt(self, req: PausedRequest, post_data: Optional[str]) -> None:
        """Extract and inspect prompt text for sensitive markers."""
        if not post_data:
            # Empty body -> safe to continue
            self.resolve_request(req.request_id, ApprovalDecision.CONTINUE)
            return

        try:
            strings = extract_prompt_strings(post_data)
            combined_prompt = "\n".join(strings)
            scan_result = self.scanner.scan_prompt(combined_prompt)

            if scan_result.is_sensitive:
                req.state = RequestLifecycleState.AWAITING_DECISION
                self._start_timeout(req)
                self.approval_required.emit(
                    req.request_id,
                    req.platform,
                    "Prompt",
                    "[Prompt Content]",
                    "WALLED_SENSITIVE marker detected in outgoing prompt",
                    combined_prompt[:250],
                )
            elif not scan_result.scan_successful:
                req.state = RequestLifecycleState.AWAITING_DECISION
                self._start_timeout(req)
                self.scan_error_occurred.emit(req.request_id, req.platform, scan_result.error or "Unknown scan error")
                self.approval_required.emit(
                    req.request_id,
                    req.platform,
                    "Prompt",
                    "[Prompt Content]",
                    f"Scan Error (Fail-Secure): {scan_result.error}",
                    "",
                )
            else:
                self.resolve_request(req.request_id, ApprovalDecision.CONTINUE)

        except Exception as e:
            req.state = RequestLifecycleState.AWAITING_DECISION
            self._start_timeout(req)
            self.scan_error_occurred.emit(req.request_id, req.platform, str(e))
            self.approval_required.emit(
                req.request_id,
                req.platform,
                "Prompt",
                "[Prompt Content]",
                f"Scanner Exception (Fail-Secure): {e}",
                "",
            )

    def _inspect_upload(
        self,
        req: PausedRequest,
        post_data: Optional[str],
        headers: Optional[dict],
    ) -> None:
        """Inspect an upload request, correlating with bridge files or multipart streams."""
        # 1. Traditional multipart form-data (e.g. direct form post or test harness)
        try:
            multipart_files = extract_multipart_files(post_data, headers)
        except Exception:
            multipart_files = []

        if multipart_files:
            self._scan_multipart_files(req, multipart_files)
            return

        # 2. Modern two-stage or direct storage upload -> Correlate with DOM FileBridge
        inferred_name, inferred_size = self._infer_upload_metadata(post_data, headers, req.url)
        if inferred_name:
            req.target_name = inferred_name

        diag_logger.info(
            "[STAGE: Request paused for inspection] req_id=%s target=%s url=%s inferred_name=%s inferred_size=%s",
            req.request_id,
            req.target_id,
            req.url,
            inferred_name,
            inferred_size,
        )

        diag_logger.info(
            "[STAGE: Pending upload match attempted] req_id=%s looking for active bridge files (total_active=%d)",
            req.request_id,
            len(self._bridge_files),
        )

        matched_bf = self._find_matching_bridge_file(req.target_id, inferred_name, inferred_size)

        if matched_bf:
            if not req.target_name or req.target_name == "Attached File":
                req.target_name = matched_bf.filename
                req.content_type = f"File Upload ({matched_bf.file_type})"

            diag_logger.info(
                "[STAGE: Pending upload matched] req_id=%s -> bridge_file='%s' (decision=%s)",
                req.request_id,
                matched_bf.filename,
                matched_bf.decision,
            )
            # File was already captured and scanned by the bridge
            if matched_bf.decision == ApprovalDecision.CONTINUE:
                if not getattr(matched_bf, "recorded_in_audit", False):
                    matched_bf.recorded_in_audit = True
                    self.safe_file_authorized.emit(
                        matched_bf.file_id, req.platform, matched_bf.filename, matched_bf.file_type
                    )
                self.resolve_request(req.request_id, ApprovalDecision.CONTINUE)
            elif matched_bf.decision == ApprovalDecision.CANCEL:
                self.resolve_request(req.request_id, ApprovalDecision.CANCEL)
            else:
                # User dialog is currently active -> hold this request until user decides
                matched_bf.pending_request_ids.add(req.request_id)
        else:
            # Bridge event has not arrived yet: race-condition protection via grace timer
            if self.correlation_timeout > 0:
                diag_logger.info(
                    "[STAGE: No immediate match found, queuing in grace window] req_id=%s (inferred_name=%s, window=%.1fs)",
                    req.request_id,
                    inferred_name,
                    self.correlation_timeout,
                )
                pu = PendingUpload(
                    request_id=req.request_id,
                    target_id=req.target_id,
                    req_state=req,
                    inferred_filename=inferred_name,
                    inferred_size=inferred_size,
                    created_at=time.time(),
                )
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(int(self.correlation_timeout * 1000))
                timer.timeout.connect(lambda: self._on_grace_timeout(req.request_id))
                pu.grace_timer = timer
                self._pending_uploads[req.request_id] = pu
                timer.start()
            else:
                self._trigger_fail_secure_upload(req)

    def _inspect_upload_init(
        self,
        req: PausedRequest,
        post_data: Optional[str],
        headers: Optional[dict],
    ) -> None:
        """Handle upload initialization/metadata request without premature fail-secure timing.

        If a bridge file is already captured and known to be sensitive, hold or block this init.
        Otherwise, auto-continue the initialization request so the user can select a file.
        """
        inferred_name, inferred_size = self._infer_upload_metadata(post_data, headers, req.url)
        if inferred_name:
            req.target_name = inferred_name

        diag_logger.info(
            "[Upload Init Request Intercepted] req_id=%s target=%s url=%s inferred_name=%s inferred_size=%s",
            req.request_id,
            req.target_id,
            req.url,
            inferred_name,
            inferred_size,
        )

        matched_bf = self._find_matching_bridge_file(req.target_id, inferred_name, inferred_size)
        if matched_bf:
            if matched_bf.decision == ApprovalDecision.CONTINUE:
                self.resolve_request(req.request_id, ApprovalDecision.CONTINUE)
            elif matched_bf.decision == ApprovalDecision.CANCEL:
                self.resolve_request(req.request_id, ApprovalDecision.CANCEL)
            elif matched_bf.is_sensitive:
                diag_logger.info(
                    "[Upload Init] Holding init request req_id=%s for pending sensitive file '%s'",
                    req.request_id,
                    matched_bf.filename,
                )
                matched_bf.pending_request_ids.add(req.request_id)
            else:
                self.resolve_request(req.request_id, ApprovalDecision.CONTINUE)
        else:
            diag_logger.info(
                "[Upload Init] Authorized metadata initialization for req_id=%s (no file content). Awaiting file transmission.",
                req.request_id,
            )
            self._immediate_continue(req.target_id, req.request_id)
            req.resolved = True
            self._paused_requests.pop(req.request_id, None)

    def _scan_multipart_files(self, req: PausedRequest, files: List[UploadedPart]) -> None:
        """Scan files parsed from traditional multipart/form-data payloads."""
        is_sensitive = False
        has_scan_error = False
        detected_file = files[0].filename
        reason = "WALLED_SENSITIVE marker detected"

        for f in files:
            file_scan = self.scanner.scan_bytes(f.content_bytes, f.filename)
            if file_scan.is_sensitive:
                is_sensitive = True
                detected_file = f.filename
                reason = f"WALLED_SENSITIVE marker found in {f.filename}"
                break
            elif not file_scan.scan_successful:
                has_scan_error = True
                detected_file = f.filename
                reason = f"File scan error on {f.filename}: {file_scan.error}"
                break

        if is_sensitive or has_scan_error:
            req.state = RequestLifecycleState.AWAITING_DECISION
            req.target_name = detected_file
            self._start_timeout(req)
            if has_scan_error:
                self.scan_error_occurred.emit(req.request_id, req.platform, reason)
            self.approval_required.emit(
                req.request_id,
                req.platform,
                "File Upload",
                detected_file,
                reason,
                "",
            )
        else:
            self.resolve_request(req.request_id, ApprovalDecision.CONTINUE)

    def _infer_upload_metadata(
        self,
        post_data: Optional[str],
        headers: Optional[dict],
        url: str,
    ) -> Tuple[Optional[str], Optional[int]]:
        """Extract filename and size hints from upload initialization JSON, headers, or URL."""
        filename = None
        size = None

        # 1. Parse JSON payload if present
        if post_data and post_data.strip().startswith(("{", "[")):
            try:
                data = json.loads(post_data.strip())
                if isinstance(data, dict):
                    filename = (
                        data.get("file_name")
                        or data.get("filename")
                        or data.get("name")
                    )
                    size = data.get("file_size") or data.get("size")
                    # Check nested objects (e.g. {"file": {"name": ...}})
                    if not filename and isinstance(data.get("file"), dict):
                        f_dict = data["file"]
                        filename = f_dict.get("name") or f_dict.get("file_name") or f_dict.get("filename")
                        size = size or f_dict.get("size") or f_dict.get("file_size")
                    if not filename and isinstance(data.get("metadata"), dict):
                        m_dict = data["metadata"]
                        filename = m_dict.get("file_name") or m_dict.get("filename") or m_dict.get("name")
            except Exception:
                pass

        # 2. Check headers (Content-Disposition, x-file-name, etc.)
        if not filename and headers:
            for k, v in headers.items():
                k_lower = k.lower()
                if k_lower == "content-disposition" and "filename=" in v:
                    import re
                    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', v, re.IGNORECASE)
                    if m:
                        filename = m.group(1).strip()
                        break
                elif k_lower in ("x-file-name", "x-filename"):
                    filename = v.strip()
                    break

        # 3. Check URL query parameters or path
        if not filename and url:
            from urllib.parse import parse_qs, urlparse
            try:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                for qk in ("file_name", "filename", "name", "file"):
                    if qk in qs and qs[qk]:
                        filename = qs[qk][0]
                        break

                if not filename and parsed.path:
                    candidate = parsed.path.rstrip("/").split("/")[-1]
                    if "." in candidate and not candidate.endswith(
                        (".com", ".net", ".ai", ".org", ".io", ".json", ".html", ".htm")
                    ):
                        filename = candidate
            except Exception:
                pass

        return filename, size

    def _find_matching_bridge_file(
        self,
        target_id: str,
        inferred_filename: Optional[str],
        inferred_size: Optional[int],
    ) -> Optional[BridgeFile]:
        """Find a BridgeFile matching this upload request across browser tabs and frames."""
        now = time.time()

        def is_active(bf: BridgeFile) -> bool:
            # Active awaiting user decision: never expires
            if bf.decision is None and (bf.is_sensitive or not (bf.scan_result and bf.scan_result.scan_successful)):
                return True
            return (now - bf.received_at) < 120.0

        # 1. Exact match on filename and size across all active bridge files
        if inferred_filename:
            for bf in reversed(list(self._bridge_files.values())):
                if is_active(bf) and bf.filename.lower() == inferred_filename.lower():
                    if inferred_size is None or bf.size == inferred_size:
                        diag_logger.info("[Correlation] Matched by filename & size: %s", bf.filename)
                        return bf

            # Loose filename match
            for bf in reversed(list(self._bridge_files.values())):
                if is_active(bf) and bf.filename.lower() == inferred_filename.lower():
                    diag_logger.info("[Correlation] Matched by loose filename: %s", bf.filename)
                    return bf

        # 2. Target ID specific match (e.g. presigned direct PUT without filename in headers)
        candidates: List[BridgeFile] = [
            bf for bf in self._bridge_files.values()
            if bf.target_id == target_id and is_active(bf)
        ]
        if candidates:
            diag_logger.info("[Correlation] Matched most recent on target tab: %s", candidates[-1].filename)
            return candidates[-1]

        # 3. Cross-target match: if exactly one bridge file is active/pending, or most recent active
        all_active = [
            bf for bf in self._bridge_files.values()
            if is_active(bf)
        ]
        if len(all_active) == 1:
            diag_logger.info("[Correlation] Matched sole active bridge file: %s", all_active[0].filename)
            return all_active[0]
        elif all_active:
            diag_logger.info("[Correlation] Matched most recent active bridge file: %s", all_active[-1].filename)
            return all_active[-1]

        return None

    def _match_pending_uploads_for_file(self, bf: BridgeFile) -> None:
        """Correlate a newly arrived BridgeFile with waiting paused upload requests."""
        matching_req_ids = []
        now = time.time()
        for req_id, pu in list(self._pending_uploads.items()):
            # A. Match by inferred filename
            if pu.inferred_filename and pu.inferred_filename.lower() == bf.filename.lower():
                matching_req_ids.append(req_id)
            # B. Match by tab target ID
            elif pu.target_id == bf.target_id:
                matching_req_ids.append(req_id)
            # C. If single pending upload in flight, correlate it
            elif len(self._pending_uploads) == 1 and (now - pu.created_at) < 30.0:
                matching_req_ids.append(req_id)

        for req_id in matching_req_ids:
            pu = self._pending_uploads.pop(req_id, None)
            if not pu:
                continue
            if pu.grace_timer:
                pu.grace_timer.stop()
                pu.grace_timer = None

            diag_logger.info(
                "[STAGE: Pending upload matched] Matched waiting upload req_id=%s with captured file '%s'",
                req_id,
                bf.filename,
            )

            # Update target name and content type with the real file info
            if not pu.req_state.target_name or pu.req_state.target_name == "Attached File":
                pu.req_state.target_name = bf.filename
                pu.req_state.content_type = f"File Upload ({bf.file_type})"

            if bf.decision == ApprovalDecision.CONTINUE:
                if not getattr(bf, "recorded_in_audit", False):
                    bf.recorded_in_audit = True
                    self.safe_file_authorized.emit(
                        bf.file_id, pu.req_state.platform, bf.filename, bf.file_type
                    )
                self.continue_fn(pu.target_id, pu.request_id)
                pu.req_state.resolved = True
                self.request_continued.emit(pu.request_id, pu.req_state.platform, pu.req_state.content_type)
                self._paused_requests.pop(pu.request_id, None)
            elif bf.decision == ApprovalDecision.CANCEL:
                self.fail_fn(pu.target_id, pu.request_id, "BlockedByClient")
                pu.req_state.resolved = True
                self.request_blocked.emit(pu.request_id, pu.req_state.platform, pu.req_state.content_type)
                self._paused_requests.pop(pu.request_id, None)
            else:
                bf.pending_request_ids.add(pu.request_id)

    def _on_grace_timeout(self, request_id: str) -> None:
        """Trigger fail-secure policy when correlation window expires without a bridge file."""
        pu = self._pending_uploads.pop(request_id, None)
        if not pu:
            return
        if pu.grace_timer:
            pu.grace_timer.stop()
            pu.grace_timer = None

        diag_logger.warning(
            "[STAGE: Grace timer expired] No bridge file arrived for req_id=%s within grace window. Triggering fail-secure.",
            request_id,
        )
        self._trigger_fail_secure_upload(pu.req_state)

    def _trigger_fail_secure_upload(self, req: PausedRequest) -> None:
        """Present fail-secure authorization dialog for unverified upload streams."""
        req.state = RequestLifecycleState.AWAITING_DECISION
        target_name = req.target_name or "Attached File"
        file_ext = ""
        if "." in target_name:
            file_ext = target_name.split(".")[-1].upper()
        content_type = f"File Upload ({file_ext})" if file_ext else "File Upload"
        req.content_type = content_type

        diag_logger.warning(
            "[STAGE: Fail-secure upload triggered] Presenting unverified upload dialog for req_id=%s target='%s' (%s)",
            req.request_id,
            target_name,
            content_type,
        )

        self._start_timeout(req)
        self.approval_required.emit(
            req.request_id,
            req.platform,
            content_type,
            target_name,
            "Unverifiable file stream (Fail-Secure Policy)",
            "",
        )

    def resolve_request(self, id_str: str, decision: ApprovalDecision) -> bool:
        """Apply terminal action (Continue or Cancel) to a paused request or bridge file.

        Guarantees strictly once-only execution.
        """
        # 1. Resolve BridgeFile if id_str is a file_id
        if id_str in self._bridge_files:
            bf = self._bridge_files[id_str]
            if bf.decision is not None and bf.decision == ApprovalDecision.CANCEL:
                return False

            bf.decision = decision
            if bf.timeout_timer:
                bf.timeout_timer.stop()
                bf.timeout_timer = None

            # Resolve all network requests waiting for this file
            pending_ids = list(bf.pending_request_ids)
            bf.pending_request_ids.clear()

            for req_id in pending_ids:
                req = self._paused_requests.get(req_id)
                if req and not req.resolved:
                    req.resolved = True
                    req.decision = decision
                    req.state = RequestLifecycleState.RESOLVED
                    if req.timeout_timer:
                        req.timeout_timer.stop()
                        req.timeout_timer = None

                    if decision == ApprovalDecision.CONTINUE:
                        self.continue_fn(req.target_id, req.request_id)
                        self.request_continued.emit(req.request_id, req.platform, req.content_type)
                    else:
                        self.fail_fn(req.target_id, req.request_id, "BlockedByClient")
                        self.request_blocked.emit(req.request_id, req.platform, req.content_type)

                    self._paused_requests.pop(req_id, None)

            for req_id in pending_ids:
                pu = self._pending_uploads.pop(req_id, None)
                if pu and pu.grace_timer:
                    pu.grace_timer.stop()
                    pu.grace_timer = None

            return True

        # 2. Resolve PausedRequest if id_str is a request_id
        req = self._paused_requests.get(id_str)
        if not req or req.resolved:
            return False

        req.resolved = True
        req.decision = decision
        req.state = RequestLifecycleState.RESOLVED
        if req.timeout_timer:
            req.timeout_timer.stop()
            req.timeout_timer = None

        if decision == ApprovalDecision.CONTINUE:
            self.continue_fn(req.target_id, req.request_id)
            self.request_continued.emit(req.request_id, req.platform, req.content_type)
        else:
            self.fail_fn(req.target_id, req.request_id, "BlockedByClient")
            self.request_blocked.emit(req.request_id, req.platform, req.content_type)

        self._paused_requests.pop(id_str, None)
        self._pending_uploads.pop(id_str, None)
        return True

    def _immediate_continue(self, target_id: str, request_id: str) -> None:
        """Immediately release an un-intercepted or safe request."""
        self.continue_fn(target_id, request_id)

    def _start_timeout(self, req: PausedRequest) -> None:
        """Start a safety timeout to auto-block abandoned dialogs after 60s."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(int(self.timeout_seconds * 1000))
        timer.timeout.connect(lambda: self._on_timeout(req.request_id))
        timer.start()
        req.timeout_timer = timer

    def _start_bridge_timeout(self, bf: BridgeFile) -> None:
        """Start a safety timeout to auto-block abandoned bridge file dialogs after 60s."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(int(self.timeout_seconds * 1000))
        timer.timeout.connect(lambda: self._on_bridge_timeout(bf.file_id))
        timer.start()
        bf.timeout_timer = timer

    def _on_timeout(self, request_id: str) -> None:
        """Fail-secure: auto-block request if user approval times out."""
        if request_id in self._paused_requests:
            self.resolve_request(request_id, ApprovalDecision.CANCEL)

    def _on_bridge_timeout(self, file_id: str) -> None:
        """Fail-secure: auto-block bridge file if user approval times out."""
        if file_id in self._bridge_files:
            self.resolve_request(file_id, ApprovalDecision.CANCEL)

    def cleanup_tab(self, target_id: str) -> None:
        """Cancel and clean up any paused requests belonging to a closed tab."""
        matching = [r_id for r_id, r in self._paused_requests.items() if r.target_id == target_id]
        for r_id in matching:
            self.resolve_request(r_id, ApprovalDecision.CANCEL)

        # Clean pending uploads on that tab
        for pu in list(self._pending_uploads.values()):
            if pu.target_id == target_id:
                if pu.grace_timer:
                    pu.grace_timer.stop()
                self._pending_uploads.pop(pu.request_id, None)

    def cleanup_all(self) -> None:
        """Cancel and clean up all active paused requests on shutdown."""
        all_ids = list(self._paused_requests.keys())
        for r_id in all_ids:
            self.resolve_request(r_id, ApprovalDecision.CANCEL)

        for pu in list(self._pending_uploads.values()):
            if pu.grace_timer:
                pu.grace_timer.stop()
        self._pending_uploads.clear()

        for bf in list(self._bridge_files.values()):
            if bf.timeout_timer:
                bf.timeout_timer.stop()
        self._bridge_files.clear()
