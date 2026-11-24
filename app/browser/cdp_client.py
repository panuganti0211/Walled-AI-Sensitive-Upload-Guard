"""Chrome DevTools Protocol (CDP) client and multi-target connection manager.

Connects to the managed Chromium instance over localhost HTTP and QWebSocket.
Discovers and attaches to ChatGPT and Perplexity tabs, monitoring candidate
prompt submissions and file uploads.
"""

import json
import urllib.request
from typing import Dict, List, Optional, Set
from urllib.error import URLError

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebSockets import QWebSocket

from app.browser.file_bridge import BRIDGE_PREFIX, FileBridge
from app.browser.models import CandidateRequest, CDPStatus
from app.browser.request_classifier import classify_request
from app.browser.response_styler import ResponseStyler
from app.browser.site_detection import is_chatgpt_url, is_perplexity_url
from app.security.diagnostic_logger import diag_logger


class TabSession(QObject):
    """Represents a WebSocket connection to a single Chromium page target."""

    message_received = Signal(str, dict)  # target_id, cdp_event_dict
    request_paused = Signal(str, str, dict)  # target_id, request_id, request_dict
    file_captured = Signal(str, dict)  # target_id, file_payload
    disconnected = Signal(str)  # target_id

    def __init__(self, target_id: str, ws_url: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.target_id = target_id
        self.ws_url = ws_url
        self._msg_id = 0

        self.ws = QWebSocket()
        self.ws.textMessageReceived.connect(self._on_message)
        self.ws.connected.connect(self._on_connected)
        self.ws.disconnected.connect(self._on_disconnected)
        self.ws.open(QUrl(ws_url))

    def _on_connected(self):
        diag_logger.info("[CDP] Connected to tab session '%s' (%s)", self.target_id, self.ws_url)
        # Enable Network, Page, and Runtime event domains
        self.send_command("Network.enable")
        self.send_command("Page.enable")
        self.send_command("Runtime.enable")
        # Add binding for the DOM file bridge
        self.send_command("Runtime.addBinding", {"name": FileBridge.BINDING_NAME})
        # Enable Fetch domain for synchronous DLP request pausing/blocking
        self.send_command(
            "Fetch.enable",
            {
                "patterns": [
                    {"urlPattern": "*chatgpt.com/*", "requestStage": "Request"},
                    {"urlPattern": "*openai.com/*", "requestStage": "Request"},
                    {"urlPattern": "*perplexity.ai/*", "requestStage": "Request"},
                    {"urlPattern": "*oaiusercontent.com/*", "requestStage": "Request"},
                ]
            },
        )
        # Inject AI-generated response text color styling
        self.inject_response_styler()
        # Inject DOM file upload capture bridge
        self.inject_file_bridge()

    def inject_response_styler(self, color: Optional[str] = None) -> None:
        """Inject AI response text color modification rules into the tab."""
        styler = ResponseStyler(color=color)
        self.send_command("Page.addScriptToEvaluateOnNewDocument", styler.get_cdp_add_script_params())
        self.send_command("Runtime.evaluate", styler.get_cdp_evaluate_params())

    def inject_file_bridge(self) -> None:
        """Inject DOM file capture bridge script into the tab."""
        bridge = FileBridge()
        self.send_command("Page.addScriptToEvaluateOnNewDocument", bridge.get_cdp_add_script_params())
        self.send_command("Runtime.evaluate", bridge.get_cdp_evaluate_params())

    def _on_disconnected(self):
        diag_logger.info("[CDP] Disconnected from tab session '%s'", self.target_id)
        self.disconnected.emit(self.target_id)

    def _on_message(self, message: str):
        try:
            data = json.loads(message)
            method = data.get("method")

            # 1. Paused network requests
            if method == "Fetch.requestPaused":
                params = data.get("params", {})
                req_id = params.get("requestId", "")
                req_data = params.get("request", {})
                diag_logger.info(
                    "[CDP Fetch.requestPaused] req_id=%s method=%s url=%s has_post=%s",
                    req_id,
                    req_data.get("method"),
                    req_data.get("url"),
                    req_data.get("hasPostData", False),
                )
                self.request_paused.emit(self.target_id, req_id, req_data)

            # 2. Bridge Channel 1: Console API (via console.debug('[WALLED_AI_BRIDGE]:...'))
            elif method == "Runtime.consoleAPICalled":
                params = data.get("params", {})
                args = params.get("args", [])
                for arg in args:
                    val = arg.get("value", "")
                    if isinstance(val, str):
                        if "[WALLED_AI_BRIDGE_DIAG]:" in val:
                            diag_logger.info("[DIAG JS->PY Console] target=%s %s", self.target_id, val)
                        elif val.startswith(BRIDGE_PREFIX):
                            payload_str = val[len(BRIDGE_PREFIX):]
                            try:
                                payload = json.loads(payload_str)
                                diag_logger.info(
                                    "[STAGE: Console event received in Python] file_id=%s filename='%s' size=%d mime='%s'",
                                    payload.get("file_id"),
                                    payload.get("name"),
                                    payload.get("size", 0),
                                    payload.get("type", "unknown"),
                                )
                                self.file_captured.emit(self.target_id, payload)
                            except Exception as e:
                                diag_logger.error("[Bridge ConsoleAPI] Failed to parse payload: %s", e)

            # 3. Bridge Channel 2: Runtime Binding (via window.walled_ai_file_bridge)
            elif method == "Runtime.bindingCalled":
                params = data.get("params", {})
                if params.get("name") == FileBridge.BINDING_NAME:
                    payload_str = params.get("payload", "")
                    if "[WALLED_AI_BRIDGE_DIAG]:" in payload_str:
                        diag_logger.info("[DIAG JS->PY Binding] target=%s %s", self.target_id, payload_str)
                    else:
                        try:
                            payload = json.loads(payload_str)
                            if isinstance(payload, dict) and payload.get("__diag"):
                                diag_logger.info(
                                    "[DIAG JS->PY Binding Object] target=%s stage=%s meta=%s",
                                    self.target_id,
                                    payload.get("stage"),
                                    payload.get("meta"),
                                )
                            else:
                                diag_logger.info(
                                    "[STAGE: Binding event received in Python] file_id=%s filename='%s' size=%d mime='%s'",
                                    payload.get("file_id"),
                                    payload.get("name"),
                                    payload.get("size", 0),
                                    payload.get("type", "unknown"),
                                )
                                self.file_captured.emit(self.target_id, payload)
                        except Exception as e:
                            diag_logger.error("[Bridge Binding] Failed to parse payload: %s", e)

            # 4. Re-inject bridge on document navigation
            elif method in ("Page.frameNavigated", "Page.loadEventFired"):
                diag_logger.debug("[CDP] Document navigation detected (%s) on tab '%s', re-insuring bridge hooks", method, self.target_id)
                self.send_command("Runtime.addBinding", {"name": FileBridge.BINDING_NAME})
                self.inject_file_bridge()

            # 5. Check command errors
            elif "error" in data:
                diag_logger.warning("[CDP Command Error] id=%s: %s", data.get("id"), data.get("error"))

            self.message_received.emit(self.target_id, data)
        except Exception as e:
            diag_logger.error("[CDP Parse Exception] %s", e)

    def continue_request(self, request_id: str) -> None:
        """Resume a paused request with original content intact."""
        self.send_command("Fetch.continueRequest", {"requestId": request_id})

    def fail_request(self, request_id: str, reason: str = "BlockedByClient") -> None:
        """Block a paused request at the browser engine level."""
        self.send_command("Fetch.failRequest", {"requestId": request_id, "errorReason": reason})

    def send_command(self, method: str, params: Optional[dict] = None) -> int:
        """Send a CDP command over WebSocket."""
        self._msg_id += 1
        msg = {
            "id": self._msg_id,
            "method": method,
            "params": params or {},
        }
        self.ws.sendTextMessage(json.dumps(msg))
        return self._msg_id

    def close(self):
        """Close the WebSocket connection."""
        try:
            self.ws.close()
        except Exception:
            pass


class CDPClient(QObject):
    """High-level CDP client managing target discovery and network observation."""

    status_changed = Signal(CDPStatus)
    chatgpt_detected = Signal(bool)
    perplexity_detected = Signal(bool)
    candidate_observed = Signal(CandidateRequest)
    prompt_observed = Signal(CandidateRequest)
    upload_observed = Signal(CandidateRequest)
    request_paused = Signal(str, str, dict)  # target_id, request_id, request_data
    file_captured = Signal(str, dict)  # target_id, file_dict

    def __init__(self, port: Optional[int] = None, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.port = port
        self.status = CDPStatus.DISCONNECTED

        self._active_sessions: Dict[str, TabSession] = {}
        self._observed_request_ids: Set[str] = set()

        # Polling timer for tab discovery & health checking
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1500)  # Check targets every 1.5 seconds
        self._poll_timer.timeout.connect(self.poll_targets)

    def start(self, port: int) -> None:
        """Begin monitoring a browser on the specified localhost port."""
        self.port = port
        self.status = CDPStatus.CONNECTING
        self.status_changed.emit(self.status)
        self._poll_timer.start()
        self.poll_targets()

    def stop(self) -> None:
        """Disconnect all CDP sessions and stop polling."""
        self._poll_timer.stop()
        for session in list(self._active_sessions.values()):
            session.close()
        self._active_sessions.clear()
        self._observed_request_ids.clear()

        self.status = CDPStatus.DISCONNECTED
        self.status_changed.emit(self.status)
        self.chatgpt_detected.emit(False)
        self.perplexity_detected.emit(False)

    def fetch_targets(self) -> List[dict]:
        """Query http://127.0.0.1:<port>/json/list for open browser pages."""
        if not self.port:
            return []
        url = f"http://127.0.0.1:{self.port}/json/list"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WalledAI-DLP"})
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    data = resp.read()
                    return json.loads(data.decode("utf-8"))
        except (URLError, TimeoutError, ConnectionRefusedError, Exception):
            return []
        return []

    def poll_targets(self) -> None:
        """Poll the browser's JSON API, update target detection, and attach tabs."""
        targets = self.fetch_targets()

        if not targets:
            if self.status != CDPStatus.DISCONNECTED:
                self.status = CDPStatus.DISCONNECTED
                self.status_changed.emit(self.status)
                self.chatgpt_detected.emit(False)
                self.perplexity_detected.emit(False)
            return

        if self.status != CDPStatus.CONNECTED:
            self.status = CDPStatus.CONNECTED
            self.status_changed.emit(self.status)

        current_target_ids: Set[str] = set()
        has_chatgpt = False
        has_perplexity = False

        for target in targets:
            target_type = target.get("type", "")
            target_url = target.get("url", "")
            target_id = target.get("id", "")
            ws_url = target.get("webSocketDebuggerUrl")

            if target_type == "page" and target_id and ws_url:
                current_target_ids.add(target_id)

                # Site detection
                if is_chatgpt_url(target_url):
                    has_chatgpt = True
                if is_perplexity_url(target_url):
                    has_perplexity = True

                # Attach to target if not already connected (prevents duplicate handlers)
                if target_id not in self._active_sessions:
                    self._attach_to_tab(target_id, ws_url)

        # Notify UI of target presence
        self.chatgpt_detected.emit(has_chatgpt)
        self.perplexity_detected.emit(has_perplexity)

        # Clean up closed tabs
        closed_ids = set(self._active_sessions.keys()) - current_target_ids
        for cid in closed_ids:
            self._detach_from_tab(cid)

    def _attach_to_tab(self, target_id: str, ws_url: str) -> None:
        """Create a new WebSocket session to inspect a tab."""
        session = TabSession(target_id, ws_url, parent=self)
        session.message_received.connect(self._handle_cdp_message)
        session.request_paused.connect(self.request_paused)
        session.file_captured.connect(self.file_captured)
        session.disconnected.connect(self._detach_from_tab)
        self._active_sessions[target_id] = session

    def continue_request(self, target_id: str, request_id: str) -> None:
        """Resume a paused request on the specified tab session."""
        session = self._active_sessions.get(target_id)
        if session:
            session.continue_request(request_id)

    def fail_request(self, target_id: str, request_id: str, reason: str = "BlockedByClient") -> None:
        """Block a paused request on the specified tab session."""
        session = self._active_sessions.get(target_id)
        if session:
            session.fail_request(request_id, reason)

    def apply_response_styling(self, color: Optional[str] = None) -> None:
        """Apply response styling to all active tab sessions."""
        for session in self._active_sessions.values():
            session.inject_response_styler(color=color)

    def _detach_from_tab(self, target_id: str) -> None:
        """Remove a closed tab session."""
        session = self._active_sessions.pop(target_id, None)
        if session:
            session.close()

    def _handle_cdp_message(self, target_id: str, data: dict) -> None:
        """Process incoming CDP events from an attached tab."""
        method = data.get("method")
        params = data.get("params", {})

        if method == "Network.requestWillBeSent":
            self._process_network_request(params)

    def _process_network_request(self, params: dict) -> None:
        """Analyze outgoing request metadata and classify candidate DLP events."""
        request_data = params.get("request", {})
        request_id = params.get("requestId", "")
        url = request_data.get("url", "")
        method = request_data.get("method", "GET")
        headers = request_data.get("headers", {})
        has_post_data = request_data.get("hasPostData", False)

        # Avoid duplicate observation reporting for the same request
        if request_id and request_id in self._observed_request_ids:
            return
        if request_id:
            self._observed_request_ids.add(request_id)
            # Prune cache if it grows too large
            if len(self._observed_request_ids) > 5000:
                self._observed_request_ids.clear()

        # Safe metadata classification
        candidate = classify_request(
            url=url,
            method=method,
            headers=headers,
            has_post_data=has_post_data,
            request_id=request_id,
        )

        self.candidate_observed.emit(candidate)

        if candidate.is_candidate_prompt:
            self.prompt_observed.emit(candidate)
        elif candidate.is_candidate_upload or candidate.is_candidate_upload_init:
            self.upload_observed.emit(candidate)
