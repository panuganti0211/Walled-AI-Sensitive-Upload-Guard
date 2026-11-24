"""Unit tests for the UnifiedScanner interface."""

from unittest.mock import patch
import pytest
from pathlib import Path
import pymupdf as fitz
from PIL import Image

from app.scanner.unified_scanner import UnifiedScanner, scan_file, scan_prompt


class TestUnifiedScanner:
    """Test suite for UnifiedScanner dispatch and policy handling."""

    @pytest.fixture
    def unified(self):
        return UnifiedScanner()

    def test_dispatch_txt_file(self, tmp_path, unified):
        """Verify .txt files are routed to TextScanner."""
        txt_path = tmp_path / "notes.txt"
        txt_path.write_text("WALLED_SENSITIVE notes", encoding="utf-8")

        result = unified.scan_file(txt_path)
        assert result.scan_successful is True
        assert result.file_type == "txt"
        assert result.is_sensitive is True

    def test_dispatch_pdf_file(self, tmp_path, unified):
        """Verify .pdf files are routed to PDFScanner."""
        pdf_path = tmp_path / "doc.pdf"
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((50, 72), "Safe PDF text")
        doc.save(str(pdf_path))
        doc.close()

        result = unified.scan_file(pdf_path)
        assert result.scan_successful is True
        assert result.file_type == "pdf"
        assert result.is_sensitive is False

    def test_dispatch_image_file(self, tmp_path, unified):
        """Verify .png / .jpg files are routed to ImageScanner."""
        img_path = tmp_path / "photo.png"
        img = Image.new("RGB", (200, 100), color="white")
        img.save(str(img_path))

        with patch.object(unified.image_scanner, "is_ocr_available", return_value=True), \
             patch("pytesseract.image_to_string", return_value="WALLED_SENSITIVE in image"):
            result = unified.scan_file(img_path)
            assert result.scan_successful is True
            assert result.file_type == "image"
            assert result.is_sensitive is True

    def test_unsupported_file_extension(self, tmp_path, unified):
        """Verify unsupported file types return scan_successful=False with clear error."""
        docx_path = tmp_path / "report.docx"
        docx_path.write_bytes(b"PK\x03\x04MockDocx")

        result = unified.scan_file(docx_path)
        assert result.scan_successful is False
        assert result.is_sensitive is False
        assert "Unsupported file format" in result.error
        assert result.file_type == "docx"

    def test_scan_prompt_safe(self, unified):
        """Verify scanning clean prompt strings."""
        result = unified.scan_prompt("Draft an email about our marketing launch.")
        assert result.scan_successful is True
        assert result.is_sensitive is False
        assert result.file_type == "prompt"

    def test_scan_prompt_sensitive(self, unified):
        """Verify scanning prompt strings containing WALLED_SENSITIVE."""
        result = unified.scan_prompt("Please review this key: WALLED_SENSITIVE_SECRET.")
        assert result.scan_successful is True
        assert result.is_sensitive is True
        assert result.detected_marker == "WALLED_SENSITIVE"
        assert result.file_type == "prompt"

    def test_convenience_functions(self, tmp_path):
        """Verify module-level scan_file and scan_prompt helpers."""
        txt = tmp_path / "test.txt"
        txt.write_text("Safe", encoding="utf-8")
        assert scan_file(txt).is_sensitive is False

        assert scan_prompt("WALLED_SENSITIVE").is_sensitive is True
