"""Unit and integration tests for the DLP EnforcementManager."""

import json
from unittest.mock import MagicMock, patch
import pytest
import pymupdf as fitz

from app.browser.enforcement_manager import EnforcementManager, RequestLifecycleState
from app.desktop.approval_dialog import ApprovalDecision


class TestEnforcementManager:
    """Test suite for request holding, DLP scanning, and Continue/Cancel enforcement."""

    @pytest.fixture
    def manager(self, qtbot):
        self.continue_mock = MagicMock()
        self.fail_mock = MagicMock()
        mgr = EnforcementManager(
            continue_fn=self.continue_mock,
            fail_fn=self.fail_mock,
            timeout_seconds=5.0,
        )
        return mgr

    def test_safe_prompt_continued_automatically(self, manager, qtbot):
        """Verify non-sensitive prompt is released immediately without user dialog."""
        payload = json.dumps({"query": "Explain quantum computing in simple terms."})
        request_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": payload,
        }

        # Signal should NOT be emitted
        dialog_requested = False

        def on_approval(*args):
            nonlocal dialog_requested
            dialog_requested = True

        manager.approval_required.connect(on_approval)
        manager.handle_request_paused("tab-1", "req-safe-1", request_data)

        assert dialog_requested is False
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-safe-1")
        assert self.fail_mock.call_count == 0

    def test_sensitive_prompt_paused_and_approved(self, manager, qtbot):
        """Verify sensitive prompt pauses, emits approval_required, and releases on Continue."""
        payload = json.dumps({"query": "Secret key: WALLED_SENSITIVE."})
        request_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": payload,
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-sens-1", request_data)

        # Verify paused state
        req_id, platform, content_type, target_name, reason, snippet = blocker.args
        assert req_id == "req-sens-1"
        assert platform == "ChatGPT"
        assert "WALLED_SENSITIVE" in reason
        assert self.continue_mock.call_count == 0  # Held in paused state

        # User chooses CONTINUE
        with qtbot.waitSignal(manager.request_continued, timeout=1000):
            resolved = manager.resolve_request("req-sens-1", ApprovalDecision.CONTINUE)

        assert resolved is True
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-sens-1")
        assert self.fail_mock.call_count == 0

    def test_sensitive_prompt_paused_and_blocked(self, manager, qtbot):
        """Verify sensitive prompt pauses, and blocks via failRequest on Cancel."""
        payload = json.dumps({"query": "Upload this: WALLED_SENSITIVE."})
        request_data = {
            "url": "https://www.perplexity.ai/api/predict",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": payload,
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000):
            manager.handle_request_paused("tab-2", "req-sens-2", request_data)

        assert self.fail_mock.call_count == 0

        # User chooses CANCEL
        with qtbot.waitSignal(manager.request_blocked, timeout=1000):
            resolved = manager.resolve_request("req-sens-2", ApprovalDecision.CANCEL)

        assert resolved is True
        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-2", "req-sens-2", "BlockedByClient")
        assert self.continue_mock.call_count == 0

    def test_strictly_once_terminal_resolution(self, manager, qtbot):
        """Verify that resolve_request can only execute once per request ID."""
        payload = json.dumps({"query": "Marker: WALLED_SENSITIVE"})
        request_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": payload,
        }

        manager.handle_request_paused("tab-1", "req-once", request_data)

        # First resolution: Cancel
        assert manager.resolve_request("req-once", ApprovalDecision.CANCEL) is True
        assert self.fail_mock.call_count == 1

        # Second resolution attempt: Must be ignored
        assert manager.resolve_request("req-once", ApprovalDecision.CONTINUE) is False
        assert self.continue_mock.call_count == 0
        assert self.fail_mock.call_count == 1

    def test_safe_txt_upload_auto_continued(self, manager, qtbot):
        """Verify upload of a harmless TXT file proceeds automatically."""
        boundary = "----WebKitFormBoundaryTest"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="clean.txt"\r\n'
            f"Content-Type: text/plain\r\n\r\n"
            f"Completely safe document.\r\n"
            f"--{boundary}--\r\n"
        )
        request_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": f"multipart/form-data; boundary={boundary}"},
            "postData": body,
        }

        manager.handle_request_paused("tab-1", "req-txt-safe", request_data)
        assert self.continue_mock.call_count == 1
        assert self.fail_mock.call_count == 0

    def test_sensitive_txt_upload_paused(self, manager, qtbot):
        """Verify upload of a TXT file containing WALLED_SENSITIVE is paused."""
        boundary = "----WebKitFormBoundaryTest"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="leak.txt"\r\n'
            f"Content-Type: text/plain\r\n\r\n"
            f"WALLED_SENSITIVE confidential credentials\r\n"
            f"--{boundary}--\r\n"
        )
        request_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": f"multipart/form-data; boundary={boundary}"},
            "postData": body,
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-txt-sens", request_data)

        assert blocker.args[0] == "req-txt-sens"
        assert blocker.args[3] == "leak.txt"
        assert self.continue_mock.call_count == 0

    def test_sensitive_pdf_upload_paused(self, manager, qtbot):
        """Verify upload of a PDF file containing WALLED_SENSITIVE is detected and paused."""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), "Confidential: WALLED_SENSITIVE")
        pdf_bytes = doc.tobytes()
        doc.close()

        boundary = "----WebKitFormBoundaryPDF"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="secret.pdf"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
            f"{pdf_bytes.decode('latin-1')}\r\n"
            f"--{boundary}--\r\n"
        )
        request_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": f"multipart/form-data; boundary={boundary}"},
            "postData": body,
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-pdf-sens", request_data)

        assert blocker.args[0] == "req-pdf-sens"
        assert blocker.args[3] == "secret.pdf"
        assert self.continue_mock.call_count == 0

    def test_unverifiable_upload_stream_fail_secure(self, manager, qtbot):
        """Verify unparsed or binary stream upload triggers fail-secure approval."""
        request_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": "application/octet-stream"},
            "postData": None,  # Binary stream not serialized as text
            "hasPostData": True,
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-binary-upload", request_data)

        assert blocker.args[0] == "req-binary-upload"
        assert "Fail-Secure" in blocker.args[4]
        assert self.continue_mock.call_count == 0

    def test_non_candidate_request_auto_continued(self, manager):
        """Verify unrelated requests (e.g. static CSS/JS) are continued without delay."""
        request_data = {
            "url": "https://chatgpt.com/static/app.css",
            "method": "GET",
        }
        manager.handle_request_paused("tab-1", "req-asset", request_data)
        assert self.continue_mock.call_count == 1
        assert self.fail_mock.call_count == 0

    def test_request_timeout_auto_blocks(self, manager, qtbot):
        """Verify timeout safely auto-blocks abandoned approval requests."""
        payload = json.dumps({"query": "WALLED_SENSITIVE data"})
        request_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": payload,
        }

        manager.handle_request_paused("tab-1", "req-timeout", request_data)

        # Force timeout trigger
        with qtbot.waitSignal(manager.request_blocked, timeout=1000):
            manager._on_timeout("req-timeout")

        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-1", "req-timeout", "BlockedByClient")

    def test_cleanup_tab_cancels_pending_requests(self, manager, qtbot):
        """Verify closing a browser tab cancels all pending paused requests on that tab."""
        payload = json.dumps({"query": "WALLED_SENSITIVE data"})
        request_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": payload,
        }

        manager.handle_request_paused("tab-closing", "req-closing", request_data)
        manager.cleanup_tab("tab-closing")

        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-closing", "req-closing", "BlockedByClient")
        assert "req-closing" not in manager._paused_requests

    def test_sensitive_image_ocr_upload_paused(self, manager, qtbot):
        """Verify upload of an image with WALLED_SENSITIVE is detected via OCR and paused."""
        from PIL import Image
        import io
        img = Image.new("RGB", (200, 100), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        boundary = "----WebKitFormBoundaryImg"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="photo.png"\r\n'
            f"Content-Type: image/png\r\n\r\n"
            f"{png_bytes.decode('latin-1')}\r\n"
            f"--{boundary}--\r\n"
        )
        request_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": f"multipart/form-data; boundary={boundary}"},
            "postData": body,
        }

        with patch("pytesseract.image_to_string", return_value="Photo with WALLED_SENSITIVE marker"), \
             patch.object(manager.scanner.image_scanner, "is_ocr_available", return_value=True):
            with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
                manager.handle_request_paused("tab-1", "req-img-sens", request_data)

            assert blocker.args[0] == "req-img-sens"
            assert blocker.args[3] == "photo.png"
            assert self.continue_mock.call_count == 0

    def test_unsupported_format_upload_fail_secure(self, manager, qtbot):
        """Verify upload of an unsupported file format triggers fail-secure approval."""
        boundary = "----WebKitFormBoundaryExe"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="archive.zip"\r\n'
            f"Content-Type: application/zip\r\n\r\n"
            f"PK\x03\x04DummyArchiveBytes\r\n"
            f"--{boundary}--\r\n"
        )
        request_data = {
            "url": "https://chatgpt.com/backend-api/files",
            "method": "POST",
            "headers": {"content-type": f"multipart/form-data; boundary={boundary}"},
            "postData": body,
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-zip-upload", request_data)

        assert blocker.args[0] == "req-zip-upload"
        assert "Fail-Secure" in blocker.args[4]
        assert self.continue_mock.call_count == 0

    def test_malformed_json_prompt_handling(self, manager, qtbot):
        """Verify prompt with broken JSON format is still extracted and scanned."""
        raw_body = '{"invalid_json": "WALLED_SENSITIVE key'
        request_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": raw_body,
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-broken-json", request_data)

        assert blocker.args[0] == "req-broken-json"
        assert "WALLED_SENSITIVE" in blocker.args[4]
        assert self.continue_mock.call_count == 0

    def test_scanner_exception_fail_secure(self, manager, qtbot):
        """Verify scanner exception triggers fail-secure approval rather than sending content."""
        payload = json.dumps({"query": "Normal text"})
        request_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": payload,
        }

        with patch.object(manager.scanner, "scan_prompt", side_effect=RuntimeError("Scanner memory error")):
            with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
                manager.handle_request_paused("tab-1", "req-scanner-error", request_data)

            assert blocker.args[0] == "req-scanner-error"
            assert "Fail-Secure" in blocker.args[4]
            assert self.continue_mock.call_count == 0

    def test_multiple_simultaneous_paused_requests(self, manager, qtbot):
        """Verify independent resolution of multiple concurrent paused requests."""
        req_data_1 = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": json.dumps({"query": "Req 1 WALLED_SENSITIVE"}),
        }
        req_data_2 = {
            "url": "https://www.perplexity.ai/api/predict",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": json.dumps({"query": "Req 2 WALLED_SENSITIVE"}),
        }

        manager.handle_request_paused("tab-1", "req-multi-1", req_data_1)
        manager.handle_request_paused("tab-2", "req-multi-2", req_data_2)

        assert len(manager._paused_requests) == 2

        # Allow req-1
        manager.resolve_request("req-multi-1", ApprovalDecision.CONTINUE)
        assert self.continue_mock.call_count == 1
        assert self.continue_mock.call_args[0] == ("tab-1", "req-multi-1")
        assert self.fail_mock.call_count == 0

        # Block req-2
        manager.resolve_request("req-multi-2", ApprovalDecision.CANCEL)
        assert self.fail_mock.call_count == 1
        assert self.fail_mock.call_args[0] == ("tab-2", "req-multi-2", "BlockedByClient")

        assert len(manager._paused_requests) == 0

    def test_cleanup_all_cancels_all_on_shutdown(self, manager):
        """Verify cleanup_all cancels all active requests upon application exit."""
        manager._paused_requests["req-a"] = MagicMock(target_id="tab-1", request_id="req-a", resolved=False, timeout_timer=None)
        manager._paused_requests["req-b"] = MagicMock(target_id="tab-2", request_id="req-b", resolved=False, timeout_timer=None)

        manager.cleanup_all()

        assert self.fail_mock.call_count == 2
        assert len(manager._paused_requests) == 0

    def test_duplicate_paused_event_ignored(self, manager):
        """Verify duplicate events for the same request ID are ignored."""
        req_data = {
            "url": "https://chatgpt.com/backend-api/conversation",
            "method": "POST",
            "headers": {"content-type": "application/json"},
            "postData": json.dumps({"query": "Marker WALLED_SENSITIVE"}),
        }

        manager.handle_request_paused("tab-1", "req-dup", req_data)
        assert "req-dup" in manager._paused_requests

        # Second delivery of same request ID
        manager.handle_request_paused("tab-1", "req-dup", req_data)
        assert len(manager._paused_requests) == 1

    def test_infer_upload_metadata_sources(self, manager):
        """Verify extraction of filename and size across JSON, headers, and URLs."""
        # 1. JSON body with file_name
        name1, size1 = manager._infer_upload_metadata(
            post_data=json.dumps({"file_name": "document.pdf", "file_size": 1024}),
            headers=None,
            url="https://chatgpt.com/backend-api/files",
        )
        assert name1 == "document.pdf"
        assert size1 == 1024

        # 2. JSON body with nested file object
        name2, size2 = manager._infer_upload_metadata(
            post_data=json.dumps({"file": {"name": "nested_file.txt", "size": 512}}),
            headers=None,
            url="https://chatgpt.com/backend-api/files",
        )
        assert name2 == "nested_file.txt"
        assert size2 == 512

        # 3. Content-Disposition header
        name3, _ = manager._infer_upload_metadata(
            post_data=None,
            headers={"Content-Disposition": 'attachment; filename="header_doc.docx"'},
            url="https://files.oaiusercontent.com/upload",
        )
        assert name3 == "header_doc.docx"

        # 4. URL query parameter
        name4, _ = manager._infer_upload_metadata(
            post_data=None,
            headers=None,
            url="https://storage.googleapis.com/bucket/upload?file_name=query_file.png",
        )
        assert name4 == "query_file.png"

    def test_unverifiable_upload_preserves_filename_and_type(self, manager, qtbot):
        """Verify unverifiable upload preserves inferred filename and file type in approval signal."""
        manager.correlation_timeout = 0.05
        init_req_data = {
            "url": "https://files.oaiusercontent.com/file-xyz/upload?file_name=unverified_test.txt",
            "method": "PUT",
            "headers": {"content-type": "text/plain"},
            "postData": "unverified data",
        }

        with qtbot.waitSignal(manager.approval_required, timeout=1000) as blocker:
            manager.handle_request_paused("tab-1", "req-unverif-type", init_req_data)

        req_id, platform, content_type, target_name, reason, snippet = blocker.args
        assert req_id == "req-unverif-type"
        assert platform == "ChatGPT"
        assert content_type == "File Upload (TXT)"
        assert target_name == "unverified_test.txt"
        assert "Unverifiable file stream (Fail-Secure Policy)" in reason
