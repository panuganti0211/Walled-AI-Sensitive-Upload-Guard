"""Unit tests for the DOM File Bridge and actual file-byte scanning pipeline."""

import base64
import json
from unittest.mock import MagicMock, patch
import fitz
import pytest

from app.browser.cdp_client import CDPClient, TabSession
from app.browser.enforcement_manager import EnforcementManager
from app.browser.file_bridge import BINDING_NAME, FileBridge
from app.browser.models import ApprovalDecision
from app.config.settings import config
from app.desktop.approval_dialog import ApprovalDialog
from app.scanner.unified_scanner import UnifiedScanner


class TestFileBridgeScript:
    """Test suite for FileBridge JavaScript generation and CDP parameters."""

    def test_file_bridge_script_generation(self):
        """Verify generated script contains hooks for inputs, drops, pastes, and bindings."""
        bridge = FileBridge()
        js = bridge.generate_injection_script()

        assert BINDING_NAME in js
        assert "FileReader" in js
        assert "readAsDataURL" in js
        assert "document.addEventListener('change'" in js
        assert "window.addEventListener('drop'" in js
        assert "window.addEventListener('paste'" in js
        assert "FormData.prototype.append" in js
        assert "showOpenFilePicker" in js
        assert "composedPath" in js
        assert "HTMLInputElement.prototype.click" in js

    def test_file_bridge_cdp_parameters(self):
        """Verify CDP Page and Runtime parameters have correct structure."""
        bridge = FileBridge()
        add_params = bridge.get_cdp_add_script_params()
        assert "source" in add_params
        assert BINDING_NAME in add_params["source"]

        eval_params = bridge.get_cdp_evaluate_params()
        assert "expression" in eval_params
        assert eval_params.get("returnByValue") is True


class TestUnifiedScannerBytes:
    """Test suite for UnifiedScanner.scan_bytes on various file types."""

    @pytest.fixture
    def scanner(self):
        return UnifiedScanner()

    def test_scan_bytes_safe_txt(self, scanner):
        """Verify scanning clean text bytes."""
        text = "Meeting agenda: quarterly projections and hiring."
        result = scanner.scan_bytes(text.encode("utf-8"), "agenda.txt")
        assert result.scan_successful is True
        assert result.is_sensitive is False

    def test_scan_bytes_sensitive_txt(self, scanner):
        """Verify scanning text bytes containing the exact marker."""
        text = f"Top secret plans: {config.sensitive_marker} details inside."
        result = scanner.scan_bytes(text.encode("utf-8"), "secret.txt")
        assert result.scan_successful is True
        assert result.is_sensitive is True

    def test_scan_bytes_safe_pdf(self, scanner):
        """Verify scanning clean PDF bytes."""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), "Safe public release document.")
        pdf_bytes = doc.tobytes()
        doc.close()

        result = scanner.scan_bytes(pdf_bytes, "doc.pdf")
        assert result.scan_successful is True
        assert result.is_sensitive is False

    def test_scan_bytes_sensitive_pdf(self, scanner):
        """Verify scanning PDF bytes containing WALLED_SENSITIVE."""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), f"Confidential: {config.sensitive_marker}")
        pdf_bytes = doc.tobytes()
        doc.close()

        result = scanner.scan_bytes(pdf_bytes, "classified.pdf")
        assert result.scan_successful is True
        assert result.is_sensitive is True
        assert result.locations == [1]

    def test_scan_bytes_unsupported_format(self, scanner):
        """Verify scanning unsupported binary formats reports scan error."""
        result = scanner.scan_bytes(b"\x00\x01\x02\x03", "binary.bin")
        assert result.scan_successful is False
        assert result.is_sensitive is False
        assert "Unsupported file format" in (result.error or "")


class TestCDPClientFileBridgeIntegration:
    """Test suite for TabSession file bridge binding and event dispatch."""

    def test_tab_session_registers_binding_on_connect(self, qtbot):
        """Verify TabSession registers Runtime.addBinding on connection."""
        with patch("PySide6.QtWebSockets.QWebSocket.open"):
            session = TabSession("tab-1", "ws://127.0.0.1:9222/tab-1")

        sent_commands = []
        session.send_command = lambda method, params=None: sent_commands.append((method, params or {})) or 1
        session._on_connected()

        methods = [cmd[0] for cmd in sent_commands]
        assert "Runtime.addBinding" in methods
        binding_cmd = next(c for c in sent_commands if c[0] == "Runtime.addBinding")
        assert binding_cmd[1]["name"] == BINDING_NAME

    def test_tab_session_emits_file_captured_on_binding_called(self, qtbot):
        """Verify Runtime.bindingCalled with file payload emits file_captured signal."""
        with patch("PySide6.QtWebSockets.QWebSocket.open"):
            session = TabSession("tab-1", "ws://127.0.0.1:9222/tab-1")

        payload = {
            "file_id": "fb_123",
            "name": "notes.txt",
            "size": 120,
            "type": "text/plain",
            "base64": base64.b64encode(b"Hello world").decode("utf-8"),
        }
        msg = json.dumps({
            "method": "Runtime.bindingCalled",
            "params": {
                "name": BINDING_NAME,
                "payload": json.dumps(payload),
            },
        })

        with qtbot.waitSignal(session.file_captured, timeout=1000) as blocker:
            session._on_message(msg)

        assert blocker.args[0] == "tab-1"
        assert blocker.args[1]["name"] == "notes.txt"
        assert blocker.args[1]["file_id"] == "fb_123"

    def test_tab_session_emits_file_captured_on_console_api_called(self, qtbot):
        """Verify Channel 1: Runtime.consoleAPICalled with bridge prefix emits file_captured signal."""
        with patch("PySide6.QtWebSockets.QWebSocket.open"):
            session = TabSession("tab-1", "ws://127.0.0.1:9222/tab-1")

        payload = {
            "file_id": "fb_console_456",
            "name": "chatgpt_upload.txt",
            "size": 85,
            "type": "text/plain",
            "base64": base64.b64encode(b"Sample content").decode("utf-8"),
        }
        msg = json.dumps({
            "method": "Runtime.consoleAPICalled",
            "params": {
                "type": "debug",
                "args": [{"type": "string", "value": f"[WALLED_AI_BRIDGE]:{json.dumps(payload)}"}],
            },
        })

        with qtbot.waitSignal(session.file_captured, timeout=1000) as blocker:
            session._on_message(msg)

        assert blocker.args[0] == "tab-1"
        assert blocker.args[1]["name"] == "chatgpt_upload.txt"
        assert blocker.args[1]["file_id"] == "fb_console_456"

    def test_tab_session_re_injects_on_frame_navigation(self):
        """Verify TabSession re-registers binding and re-evaluates bridge on document navigation."""
        with patch("PySide6.QtWebSockets.QWebSocket.open"):
            session = TabSession("tab-1", "ws://127.0.0.1:9222/tab-1")

        sent_commands = []
        session.send_command = lambda method, params=None: sent_commands.append((method, params or {})) or 1

        msg = json.dumps({"method": "Page.frameNavigated", "params": {"frame": {"id": "f1"}}})
        session._on_message(msg)

        methods = [c[0] for c in sent_commands]
        assert "Runtime.addBinding" in methods
        assert "Runtime.evaluate" in methods


class TestEnforcementManagerFileBridge:
    """Test suite for file bridge scanning, upload correlation, and race-condition prevention."""

    @pytest.fixture
    def manager(self):
        self.continue_mock = MagicMock()
        self.fail_mock = MagicMock()
        mgr = EnforcementManager(
            continue_fn=self.continue_mock,
            fail_fn=self.fail_mock,
            correlation_timeout=0.1,  # Fast timeout for test speed
        )
        return mgr

    def test_safe_file_bridge_auto_continues_upload(self, manager, qtbot):
        """Clean file uploaded via bridge allows subsequent network upload requests automatically."""
        raw_text = b"Public financial disclosures without markers."
        file_payload = {
            "file_id": "fb_clean_1",
            "name": "public_report.txt",
            "size": len(raw_text),
            "type": "text/plain",
            "base64": base64.b64encode(raw_text).decode("utf-8"),
        }

        # 1. User picks file (bridge event arrives)
        manager.handle_file_captured("tab-1", file_payload)

        # 2. ChatGPT makes Stage 1 initialization request (POST /backend-api/files with JSON metadata)
        init_req_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": json.dumps({"file_name": "public_report.txt", "file_size": len(raw_text)}),
        }
        manager.handle_request_paused("tab-1", "req-init-1", init_req_data)

        # Stage 1 request should be auto-continued immediately without prompting
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-init-1")
        assert self.fail_mock.call_count == 0

        # 3. ChatGPT makes Stage 2 direct storage request (PUT files.oaiusercontent.com)
        put_req_data = {
            "url": "https://files.oaiusercontent.com/file-xyz/upload",
            "method": "PUT",
            "headers": {"content-type": "text/plain"},
            "postData": None,
        }
        manager.handle_request_paused("tab-1", "req-put-1", put_req_data)

        # Stage 2 request should also be auto-continued
        assert self.continue_mock.call_count == 2
        assert self.continue_mock.call_args[0] == ("tab-1", "req-put-1")
        assert self.fail_mock.call_count == 0

    def test_sensitive_file_bridge_paused_and_blocked_on_cancel(self, manager, qtbot):
        """Sensitive file upload pauses network requests and blocks on Cancel."""
        raw_text = f"Classified blueprint: {config.sensitive_marker}".encode("utf-8")
        file_payload = {
            "file_id": "fb_sens_1",
            "name": "blueprint.txt",
            "size": len(raw_text),
            "type": "text/plain",
            "base64": base64.b64encode(raw_text).decode("utf-8"),
        }

        # 1. User picks sensitive file -> triggers approval dialog
        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_file_captured("tab-1", file_payload)

        assert blocker.args[0] == "fb_sens_1"
        assert blocker.args[3] == "blueprint.txt"
        assert config.sensitive_marker in blocker.args[4]

        # 2. Stage 1 network request arrives while dialog is waiting
        init_req_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": json.dumps({"file_name": "blueprint.txt", "file_size": len(raw_text)}),
        }
        manager.handle_request_paused("tab-1", "req-init-sens", init_req_data)

        # Request must remain held in CDP (not yet continued or failed)
        assert self.continue_mock.call_count == 0
        assert self.fail_mock.call_count == 0

        # 3. User clicks Cancel in the native dialog
        manager.resolve_request("fb_sens_1", ApprovalDecision.CANCEL)

        # Block command must be sent to Chromium CDP
        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-1", "req-init-sens", "BlockedByClient")
        assert self.continue_mock.call_count == 0

    def test_sensitive_file_bridge_paused_and_resumed_on_continue(self, manager, qtbot):
        """Sensitive file upload pauses network requests and resumes when user clicks Continue."""
        raw_text = f"Internal report: {config.sensitive_marker}".encode("utf-8")
        file_payload = {
            "file_id": "fb_sens_2",
            "name": "internal.txt",
            "size": len(raw_text),
            "type": "text/plain",
            "base64": base64.b64encode(raw_text).decode("utf-8"),
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000):
            manager.handle_file_captured("tab-1", file_payload)

        # Network request arrives
        init_req_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": json.dumps({"file_name": "internal.txt", "file_size": len(raw_text)}),
        }
        manager.handle_request_paused("tab-1", "req-init-auth", init_req_data)

        # User authorizes transmission
        manager.resolve_request("fb_sens_2", ApprovalDecision.CONTINUE)

        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-init-auth")
        assert self.fail_mock.call_count == 0

    def test_race_condition_network_request_arrives_before_bridge_file(self, manager, qtbot):
        """Network request arriving before bridge file is held during grace window, then resolved."""
        # Configure a grace window of 0.3s
        manager.correlation_timeout = 0.3

        # 1. Actual storage upload request arrives FIRST
        init_req_data = {
            "url": "https://files.oaiusercontent.com/file-xyz/upload?file_name=fast_network.txt",
            "method": "PUT",
            "headers": {"content-type": "text/plain"},
            "postData": None,
        }
        manager.handle_request_paused("tab-1", "req-fast-net", init_req_data)

        # Request is paused in grace window, not yet continued or failed
        assert self.continue_mock.call_count == 0
        assert self.fail_mock.call_count == 0

        # 2. Bridge event arrives 50ms later (clean file)
        raw_text = b"Public document that was read after network request."
        file_payload = {
            "file_id": "fb_fast_1",
            "name": "fast_network.txt",
            "size": 50,
            "type": "text/plain",
            "base64": base64.b64encode(raw_text).decode("utf-8"),
        }
        manager.handle_file_captured("tab-1", file_payload)

        # Correlated and continued!
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-fast-net")

    def test_fail_secure_when_no_bridge_file_arrives(self, manager, qtbot):
        """Unverifiable upload stream without bridge event triggers fail-secure approval."""
        manager.correlation_timeout = 0.05

        unverified_req_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": "application/octet-stream"},
            "postData": None,
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-unverified", unverified_req_data)

        assert blocker.args[0] == "req-unverified"
        assert "Fail-Secure" in blocker.args[4]
        assert self.continue_mock.call_count == 0

    def test_dual_channel_deduplication(self, manager, qtbot):
        """Verify duplicate payloads from Channel 1 and Channel 2 for same file are processed only once."""
        raw_text = f"Secrets: {config.sensitive_marker}".encode("utf-8")
        payload = {
            "file_id": "fb_duplicate_777",
            "name": "secret_credentials.txt",
            "size": len(raw_text),
            "type": "text/plain",
            "base64": base64.b64encode(raw_text).decode("utf-8"),
        }

        # First delivery (e.g. from Channel 1: ConsoleAPI)
        with qtbot.waitSignal(manager.approval_required, timeout=1000):
            manager.handle_file_captured("tab-1", payload)

        assert "fb_duplicate_777" in manager._bridge_files
        assert len(manager._bridge_files) == 1

        # Second delivery (e.g. from Channel 2: Runtime.bindingCalled with identical file_id)
        # Should be silently deduplicated without triggering a second approval dialog or re-scan
        manager.handle_file_captured("tab-1", payload)
        assert len(manager._bridge_files) == 1

    def test_sensitive_txt_upload_approval_dialog_shows_real_filename_and_marker(self, manager, qtbot):
        """Verify sensitive TXT upload displays real filename and exact marker detection in native dialog."""
        raw_text = f"Customer dataset with {config.sensitive_marker} embedded".encode("utf-8")
        payload = {
            "file_id": "fb_sens_txt_99",
            "name": "customer_export.txt",
            "size": len(raw_text),
            "type": "text/plain",
            "base64": base64.b64encode(raw_text).decode("utf-8"),
        }

        # 1. Capture file via bridge
        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_file_captured("tab-1", payload)

        req_id, platform, content_type, target_name, reason, snippet = blocker.args
        assert req_id == "fb_sens_txt_99"
        assert platform == "ChatGPT"
        assert content_type == "File Upload (TXT)"
        assert target_name == "customer_export.txt"
        assert "WALLED_SENSITIVE marker detected" in reason
        assert config.sensitive_marker in snippet

        # 2. Verify dialog representation
        dlg = ApprovalDialog(
            platform=platform,
            content_type=content_type,
            file_name=target_name,
            detection_reason=reason,
            snippet=snippet,
        )
        qtbot.addWidget(dlg)

        # Check window title and header alert banner
        assert "Security Alert" in dlg.windowTitle()
        assert "customer_export.txt" in dlg.file_name
        assert "WALLED_SENSITIVE marker detected" in dlg.detection_reason

    def test_unverifiable_upload_approval_dialog_shows_unverifiable_title(self, manager, qtbot):
        """Verify unverifiable upload presents dialog with 'Unverifiable Upload' banner rather than marker detected."""
        manager.correlation_timeout = 0.05
        unverified_req_data = {
            "url": "https://files.oaiusercontent.com/file-xyz/upload?file_name=mystery_stream.bin",
            "method": "PUT",
            "headers": {"content-type": "application/octet-stream"},
            "postData": None,
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-unverif-dlg", unverified_req_data)

        req_id, platform, content_type, target_name, reason, snippet = blocker.args
        assert req_id == "req-unverif-dlg"
        assert content_type == "File Upload (BIN)"
        assert target_name == "mystery_stream.bin"
        assert "Unverifiable file stream (Fail-Secure Policy)" in reason

        dlg = ApprovalDialog(
            platform=platform,
            content_type=content_type,
            file_name=target_name,
            detection_reason=reason,
        )
        qtbot.addWidget(dlg)

        assert "Unverifiable Upload Alert" in dlg.windowTitle()

    def test_cross_target_correlation_matching(self, manager, qtbot):
        """Verify upload correlation succeeds even across frame/target boundaries when filename matches."""
        manager.correlation_timeout = 0.2
        raw_text = b"Quarterly summary data without markers."
        file_payload = {
            "file_id": "fb_frame_1",
            "name": "financial_summary.txt",
            "size": len(raw_text),
            "type": "text/plain",
            "base64": base64.b64encode(raw_text).decode("utf-8"),
        }

        # Bridge file received from subframe target
        manager.handle_file_captured("tab-subframe-1", file_payload)

        # Paused request received from main frame target with matching filename
        init_req_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": json.dumps({"file_name": "financial_summary.txt", "file_size": len(raw_text)}),
        }
        manager.handle_request_paused("tab-mainframe-1", "req-cross-target", init_req_data)

        # Should match and auto-continue cleanly without prompting
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-mainframe-1", "req-cross-target")


class TestUploadInitializationAndTransmissionDLP:
    """Dedicated test suite validating upload initialization vs actual transmission DLP enforcement."""

    @pytest.fixture
    def manager(self):
        self.continue_mock = MagicMock()
        self.fail_mock = MagicMock()
        mgr = EnforcementManager(
            continue_fn=self.continue_mock,
            fail_fn=self.fail_mock,
            correlation_timeout=0.05,
        )
        # Pre-seed tab-1 as ChatGPT platform
        mgr._target_platforms["tab-1"] = "ChatGPT"
        return mgr

    def test_chatgpt_metadata_init_post_before_file_selection_does_not_trigger_dlp_popup(self, manager, qtbot):
        """Verify POST /backend-api/files metadata init before file selection auto-continues without DLP popup."""
        init_req_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": json.dumps({"file_name": "pre_select.pdf", "file_size": 2048, "use_case": "my_files"}),
        }

        # Handle initialization request
        manager.handle_request_paused("tab-1", "req-init-before-pick", init_req_data)

        # 1. Request was immediately auto-continued
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-init-before-pick")

        # 2. No pending grace timer or pending uploads created
        assert "req-init-before-pick" not in manager._pending_uploads

        # 3. Wait past the correlation timeout: no fail-secure popup should fire
        qtbot.wait(100)
        assert self.fail_mock.call_count == 0

    def test_actual_binary_storage_transmission_remains_intercepted(self, manager):
        """Verify storage upload endpoint is classified as upload and intercepted."""
        storage_req_data = {
            "url": "https://files.oaiusercontent.com/file-abc123xyz/upload",
            "method": "PUT",
            "headers": {"content-type": "application/octet-stream"},
            "postData": None,
        }

        manager.handle_request_paused("tab-1", "req-storage-hold", storage_req_data)

        # Must not be immediately continued; must be held in CDP
        assert self.continue_mock.call_count == 0
        assert "req-storage-hold" in manager._paused_requests
        assert "req-storage-hold" in manager._pending_uploads

    def test_safe_file_proceeds_only_after_verified_scan(self, manager, qtbot):
        """Verify safe file is verified by UnifiedScanner before storage transmission continues."""
        clean_text = b"Public quarterly update without any restricted data."
        file_payload = {
            "file_id": "fb_clean_verified",
            "name": "public_update.txt",
            "size": len(clean_text),
            "type": "text/plain",
            "base64": base64.b64encode(clean_text).decode("utf-8"),
        }

        # 1. Bridge captures and scans file
        manager.handle_file_captured("tab-1", file_payload)
        bf = manager._bridge_files.get("fb_clean_verified")
        assert bf is not None
        assert bf.is_sensitive is False
        assert bf.decision == ApprovalDecision.CONTINUE

        # 2. Actual binary storage upload arrives
        storage_req_data = {
            "url": "https://files.oaiusercontent.com/file-xyz/upload?file_name=public_update.txt",
            "method": "PUT",
            "headers": {"content-type": "application/octet-stream"},
            "postData": None,
        }
        manager.handle_request_paused("tab-1", "req-storage-clean", storage_req_data)

        # 3. Transmitted cleanly without popup
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-storage-clean")
        assert self.fail_mock.call_count == 0

    def test_sensitive_file_requires_approval_and_blocks_on_cancel(self, manager, qtbot):
        """Verify sensitive file triggers approval popup with real filename and cancels transmission on user Cancel."""
        sens_text = f"Confidential client list: {config.sensitive_marker} 2026".encode("utf-8")
        file_payload = {
            "file_id": "fb_sens_verified",
            "name": "client_list.txt",
            "size": len(sens_text),
            "type": "text/plain",
            "base64": base64.b64encode(sens_text).decode("utf-8"),
        }

        # 1. Bridge captures file -> UnifiedScanner detects WALLED_SENSITIVE -> popup emitted
        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_file_captured("tab-1", file_payload)

        req_id, platform, content_type, target_name, reason, snippet = blocker.args
        assert req_id == "fb_sens_verified"
        assert target_name == "client_list.txt"
        assert config.sensitive_marker in reason
        assert config.sensitive_marker in snippet

        # 2. Actual storage transmission arrives while user is deciding
        storage_req_data = {
            "url": "https://files.oaiusercontent.com/file-xyz/upload?file_name=client_list.txt",
            "method": "PUT",
            "headers": {"content-type": "application/octet-stream"},
            "postData": None,
        }
        manager.handle_request_paused("tab-1", "req-storage-sens", storage_req_data)

        # Transmission must be held (not continued)
        assert self.continue_mock.call_count == 0
        assert self.fail_mock.call_count == 0

        # 3. User clicks Cancel in native dialog
        manager.resolve_request("fb_sens_verified", ApprovalDecision.CANCEL)

        # Transmission must be blocked in CDP
        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-1", "req-storage-sens", "BlockedByClient")
        assert self.continue_mock.call_count == 0

    def test_unverifiable_actual_transmission_remains_fail_secure(self, manager, qtbot):
        """Verify actual file transmission without matching bridge file triggers fail-secure block after timeout."""
        manager.correlation_timeout = 0.05
        storage_req_data = {
            "url": "https://files.oaiusercontent.com/file-xyz/upload?file_name=unlinked_doc.pdf",
            "method": "PUT",
            "headers": {"content-type": "application/pdf"},
            "postData": None,
        }

        # Actual transmission arrives with no bridge file ever captured
        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-storage-unverif", storage_req_data)

        req_id, platform, content_type, target_name, reason, snippet = blocker.args
        assert req_id == "req-storage-unverif"
        assert "unlinked_doc.pdf" in target_name
        assert "Unverifiable file stream (Fail-Secure Policy)" in reason

        # User cancels the unverifiable upload
        manager.resolve_request("req-storage-unverif", ApprovalDecision.CANCEL)
        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-1", "req-storage-unverif", "BlockedByClient")

    def test_regional_oaiusercontent_upload_classified_as_upload(self):
        """Verify regional Azure storage endpoints for ChatGPT are classified as upload."""
        from app.browser.request_classifier import classify_request

        # 1. Regional storage PUT carrying payload
        r1 = classify_request(
            url="https://sdmntprcentralindia.oaiusercontent.com/files/00000000-d3dc-8211-b2ff-3caf0a8050bf/raw",
            method="PUT",
            has_post_data=True,
        )
        assert r1.request_type == "upload"
        assert r1.is_candidate_upload is True
        assert r1.platform == "ChatGPT"

        # 2. Regional storage PUT without postData flag (streaming PUT)
        r2 = classify_request(
            url="https://sdmntprindiasocentral.oaiusercontent.com/files/00000000-d3dc-8211-b2ff-3caf0a8050bf/raw",
            method="PUT",
            has_post_data=False,
        )
        assert r2.request_type == "upload"
        assert r2.is_candidate_upload is True
        assert r2.platform == "ChatGPT"

        # 3. CORS preflight OPTIONS to storage host remains 'other'
        r3 = classify_request(
            url="https://sdmntprcentralindia.oaiusercontent.com/files/00000000-d3dc-8211-b2ff-3caf0a8050bf/raw",
            method="OPTIONS",
        )
        assert r3.request_type == "other"

        # 4. GET from storage host remains 'other'
        r4 = classify_request(
            url="https://sdmntprcentralindia.oaiusercontent.com/files/00000000-d3dc-8211-b2ff-3caf0a8050bf/raw",
            method="GET",
        )
        assert r4.request_type == "other"

        # 5. Metadata initialization remains 'upload_init'
        r5 = classify_request(
            url="https://chatgpt.com/backend-api/files",
            method="POST",
            headers={"content-type": "application/json"},
            has_post_data=True,
        )
        assert r5.request_type == "upload_init"
        assert r5.is_candidate_upload_init is True

        # 6. Reservation claim_and_finish remains 'upload_init'
        r6 = classify_request(
            url="https://chatgpt.com/backend-api/files/upload_reservations/xyz/claim_and_finish",
            method="POST",
            has_post_data=True,
        )
        assert r6.request_type == "upload_init"

    def test_sensitive_upload_fast_cancel_blocks_regional_storage_put(self, manager, qtbot):
        """User quickly cancels sensitive file dialog; subsequent regional storage PUT is immediately blocked."""
        # 1. Bridge captures sensitive file
        content = f"Confidential text {config.sensitive_marker} internal only".encode("utf-8")
        payload = {
            "file_id": "fb_fast_cancel",
            "name": "sensitive_report.txt",
            "size": len(content),
            "type": "text/plain",
            "base64": base64.b64encode(content).decode("utf-8"),
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_file_captured("tab-1", payload)

        assert blocker.args[0] == "fb_fast_cancel"
        assert blocker.args[3] == "sensitive_report.txt"

        # 2. Fast cancel: user cancels within milliseconds before network request arrives
        manager.resolve_request("fb_fast_cancel", ApprovalDecision.CANCEL)

        # 3. Regional storage PUT arrives after user cancellation
        regional_put = {
            "url": "https://sdmntprcentralindia.oaiusercontent.com/files/00000000-d3dc-8211-b2ff-3caf0a8050bf/raw",
            "method": "PUT",
            "headers": {"content-type": "text/plain"},
            "hasPostData": True,
        }
        manager.handle_request_paused("tab-1", "req-reg-put-1", regional_put)

        # Must be immediately blocked via fail_fn with BlockedByClient
        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-1", "req-reg-put-1", "BlockedByClient")
        assert self.continue_mock.call_count == 0

    def test_sensitive_upload_held_and_continue_allows_regional_storage_put(self, manager, qtbot):
        """Sensitive upload holds regional storage PUT until user approves with Continue."""
        content = f"Protected data: {config.sensitive_marker}".encode("utf-8")
        payload = {
            "file_id": "fb_held_cont",
            "name": "protected_plan.txt",
            "size": len(content),
            "type": "text/plain",
            "base64": base64.b64encode(content).decode("utf-8"),
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_file_captured("tab-1", payload)

        # Regional PUT arrives while dialog is pending
        regional_put = {
            "url": "https://sdmntprindiasocentral.oaiusercontent.com/files/00000000-d3dc-8211-b2ff-3caf0a8050bf/raw",
            "method": "PUT",
            "headers": {"content-type": "text/plain"},
            "hasPostData": True,
        }
        manager.handle_request_paused("tab-1", "req-reg-put-2", regional_put)

        # Held! Neither continue nor fail called yet
        assert self.continue_mock.call_count == 0
        assert self.fail_mock.call_count == 0

        # User confirms Continue
        manager.resolve_request("fb_held_cont", ApprovalDecision.CONTINUE)

        # Resumed!
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-reg-put-2")
        assert self.fail_mock.call_count == 0

    def test_safe_file_auto_continues_regional_storage_put(self, manager, qtbot):
        """Clean file auto-authorizes regional storage PUT without prompting user."""
        safe_content = b"Completely harmless text with no markers."
        payload = {
            "file_id": "fb_safe_reg",
            "name": "safe_document.txt",
            "size": len(safe_content),
            "type": "text/plain",
            "base64": base64.b64encode(safe_content).decode("utf-8"),
        }

        # Bridge captures file -> verified clean -> no approval dialog
        manager.handle_file_captured("tab-1", payload)
        assert manager._bridge_files["fb_safe_reg"].decision == ApprovalDecision.CONTINUE

        # Regional PUT arrives
        regional_put = {
            "url": "https://sdmntprcentralindia.oaiusercontent.com/files/00000000-d3dc-8211-b2ff-3caf0a8050bf/raw",
            "method": "PUT",
            "headers": {"content-type": "text/plain"},
            "hasPostData": True,
        }
        manager.handle_request_paused("tab-1", "req-reg-put-safe", regional_put)

        # Immediately continued
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-reg-put-safe")
        assert self.fail_mock.call_count == 0

    def test_non_blocking_approval_dialog_keeps_event_loop_responsive(self, qtbot):
        """Non-blocking modal ApprovalDialog allows Qt event processing while displayed."""
        dialog = ApprovalDialog(
            platform="ChatGPT",
            content_type="File Upload (TXT)",
            file_name="test_sensitive.txt",
            detection_reason=f"{config.sensitive_marker} detected in test_sensitive.txt",
        )
        qtbot.addWidget(dialog)

        # Show modal dialog non-blocking
        dialog.show()
        assert dialog.isVisible() is True

        # Event loop processes without stalling
        qtbot.wait(50)

        # Clicking Cancel emits decision_made with CANCEL
        with qtbot.waitSignal(dialog.decision_made, timeout=1000) as blocker:
            dialog.btn_cancel.click()

        assert blocker.args[0] == ApprovalDecision.CANCEL
        dialog.close()

    def test_safe_file_records_files_allowed_in_dashboard(self, qtbot):
        """Clean file upload correctly updates Files Allowed counter and audit log."""
        from app.desktop.main_window import MainWindow

        window = MainWindow()
        qtbot.addWidget(window)

        initial_allowed = window.files_allowed
        initial_sensitive = window.sensitive_uploads_detected
        initial_unverifiable = window.unverifiable_uploads

        # Emit safe upload authorized event
        window.browser_controller.safe_file_authorized.emit(
            "fb_safe_audit", "ChatGPT", "clean_notes.txt", "TXT"
        )

        assert window.files_allowed == initial_allowed + 1
        assert window.sensitive_uploads_detected == initial_sensitive
        assert window.unverifiable_uploads == initial_unverifiable

        # Verify audit table entry
        assert window.audit_table.rowCount() >= 1
        last_row = window.audit_table.rowCount() - 1
        assert window.audit_table.item(last_row, 3).text() == "clean_notes.txt"
        assert window.audit_table.item(last_row, 5).text() == "Allowed (Clean)"
        window.close()

    def test_unknown_platform_upload_not_automatically_continued(self, manager, qtbot):
        """Storage upload with platform Unknown is held in grace window, NOT auto-continued."""
        manager.correlation_timeout = 0.5
        manager._target_platforms.clear()

        s3_req_data = {
            "url": "https://s3.amazonaws.com/my-bucket/contracts/report.pdf",
            "method": "PUT",
            "headers": {"content-type": "application/pdf"},
            "hasPostData": True,
        }
        manager.handle_request_paused("tab-untracked", "req-s3-1", s3_req_data)

        # Must NOT be automatically continued
        assert self.continue_mock.call_count == 0
        assert self.fail_mock.call_count == 0
        assert "req-s3-1" in manager._paused_requests
        assert manager._paused_requests["req-s3-1"].platform == "Cloud Storage"

    def test_unknown_platform_candidate_upload_proceeds_to_dlp_enforcement(self, manager, qtbot):
        """Unknown-platform upload correlated with sensitive bridge file is held and blocked on Cancel."""
        manager._target_platforms.clear()

        content = f"S3 Confidential text {config.sensitive_marker}".encode("utf-8")
        payload = {
            "file_id": "fb_s3_sens",
            "name": "confidential.txt",
            "size": len(content),
            "type": "text/plain",
            "base64": base64.b64encode(content).decode("utf-8"),
        }

        # Bridge captures file -> marked sensitive
        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_file_captured("tab-s3", payload)

        assert blocker.args[0] == "fb_s3_sens"

        # S3 upload arrives with unknown platform
        s3_req_data = {
            "url": "https://s3.amazonaws.com/my-bucket/confidential.txt",
            "method": "PUT",
            "headers": {"content-type": "text/plain"},
            "hasPostData": True,
        }
        manager.handle_request_paused("tab-s3", "req-s3-sens", s3_req_data)

        # Held! Not continued or failed yet
        assert self.continue_mock.call_count == 0
        assert self.fail_mock.call_count == 0

        # User cancels
        manager.resolve_request("fb_s3_sens", ApprovalDecision.CANCEL)

        # Must be explicitly failed with BlockedByClient
        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-s3", "req-s3-sens", "BlockedByClient")
        assert self.continue_mock.call_count == 0

    def test_unverifiable_unknown_upload_fails_securely(self, manager, qtbot):
        """Unknown-platform upload with no matching bridge file triggers fail-secure alert and blocks."""
        manager.correlation_timeout = 0.05
        manager._target_platforms.clear()

        blob_req_data = {
            "url": "https://myaccount.blob.core.windows.net/uploads/data.zip",
            "method": "PUT",
            "headers": {"content-type": "application/octet-stream"},
            "hasPostData": True,
        }

        # Must trigger fail-secure alert
        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-untracked-2", "req-blob-unverif", blob_req_data)

        req_id, platform, content_type, target_name, reason, snippet = blocker.args
        assert req_id == "req-blob-unverif"
        assert platform == "Cloud Storage"
        assert "Unverifiable file stream (Fail-Secure Policy)" in reason

        # User cancels unverifiable upload
        manager.resolve_request("req-blob-unverif", ApprovalDecision.CANCEL)
        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-untracked-2", "req-blob-unverif", "BlockedByClient")
        assert self.continue_mock.call_count == 0

    def test_ordinary_other_and_navigation_requests_automatically_continue(self, manager):
        """Static assets, navigation, and ordinary non-upload requests on unknown platforms auto-continue."""
        # 1. Static asset on unknown domain -> other
        asset_req = {
            "url": "https://cdn.example.com/static/analytics.js",
            "method": "GET",
            "headers": {"content-type": "application/javascript"},
        }
        manager.handle_request_paused("tab-misc", "req-asset-1", asset_req)
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-misc", "req-asset-1")

        # 2. HTML navigation on unknown domain -> navigation
        nav_req = {
            "url": "https://example.com/portal/home.html",
            "method": "GET",
            "headers": {"content-type": "text/html"},
        }
        manager.handle_request_paused("tab-misc", "req-nav-1", nav_req)
        assert self.continue_mock.call_count == 2
        assert self.continue_mock.call_args[0] == ("tab-misc", "req-nav-1")

        # 3. Ordinary non-upload API POST on unknown domain -> other
        api_req = {
            "url": "https://api.example.com/v1/ping",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": '{"ping": true}',
        }
        manager.handle_request_paused("tab-misc", "req-api-1", api_req)
        assert self.continue_mock.call_count == 3
        assert self.continue_mock.call_args[0] == ("tab-misc", "req-api-1")

