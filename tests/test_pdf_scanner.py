"""Unit tests for the PDF document content scanner using PyMuPDF."""

import pytest
from pathlib import Path
import pymupdf as fitz

from app.scanner.pdf_scanner import PDFScanner


class TestPDFScanner:
    """Test suite for PDFScanner."""

    @pytest.fixture
    def scanner(self):
        return PDFScanner()

    def test_safe_single_page_pdf(self, tmp_path, scanner):
        """Verify a clean PDF with no sensitive marker is reported as safe."""
        pdf_path = tmp_path / "safe.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), "This is a clean corporate report for research.")
        doc.save(str(pdf_path))
        doc.close()

        result = scanner.scan_file(pdf_path)
        assert result.scan_successful is True
        assert result.is_sensitive is False
        assert result.file_type == "pdf"
        assert result.locations == []
        assert result.detected_marker is None

    def test_sensitive_first_page_pdf(self, tmp_path, scanner):
        """Verify detection when marker is on the first page."""
        pdf_path = tmp_path / "sensitive_p1.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), "Confidential: WALLED_SENSITIVE data enclosed.")
        doc.save(str(pdf_path))
        doc.close()

        result = scanner.scan_file(pdf_path)
        assert result.scan_successful is True
        assert result.is_sensitive is True
        assert result.detected_marker == "WALLED_SENSITIVE"
        assert result.locations == [1]

    def test_sensitive_later_page_pdf(self, tmp_path, scanner):
        """Verify detection when marker is on later pages (page 3) in a multi-page PDF."""
        pdf_path = tmp_path / "multipage_sensitive.pdf"
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((50, 72), "Page 1: Overview and introduction (safe).")
        p2 = doc.new_page()
        p2.insert_text((50, 72), "Page 2: Methodology and diagrams (safe).")
        p3 = doc.new_page()
        p3.insert_text((50, 72), "Page 3: Secret credentials: WALLED_SENSITIVE.")
        doc.save(str(pdf_path))
        doc.close()

        result = scanner.scan_file(pdf_path)
        assert result.scan_successful is True
        assert result.is_sensitive is True
        assert result.locations == [3]

    def test_multiple_pages_containing_marker(self, tmp_path, scanner):
        """Verify all page numbers containing marker are recorded in locations."""
        pdf_path = tmp_path / "multi_hits.pdf"
        doc = fitz.open()
        p1 = doc.new_page()
        p1.insert_text((50, 72), "WALLED_SENSITIVE on page 1")
        p2 = doc.new_page()
        p2.insert_text((50, 72), "Safe page 2")
        p3 = doc.new_page()
        p3.insert_text((50, 72), "WALLED_SENSITIVE on page 3")
        doc.save(str(pdf_path))
        doc.close()

        result = scanner.scan_file(pdf_path)
        assert result.scan_successful is True
        assert result.is_sensitive is True
        assert result.locations == [1, 3]

    def test_empty_pdf_zero_pages(self, scanner):
        """Verify an in-memory empty PDF with zero pages is handled safely."""
        doc = fitz.open()  # 0 pages in-memory document
        result = scanner._scan_doc(doc)
        assert result.scan_successful is True
        assert result.is_sensitive is False
        assert any("0 pages" in w for w in result.warnings)

    def test_blank_page_pdf(self, tmp_path, scanner):
        """Verify a PDF with a blank page (no text) is handled safely."""
        pdf_path = tmp_path / "blank.pdf"
        doc = fitz.open()
        doc.new_page()  # Blank page without any text
        doc.save(str(pdf_path))
        doc.close()

        result = scanner.scan_file(pdf_path)
        assert result.scan_successful is True
        assert result.is_sensitive is False
        assert result.locations == []

    def test_corrupted_invalid_pdf(self, tmp_path, scanner):
        """Verify a corrupted/invalid PDF file returns scan_successful=False."""
        pdf_path = tmp_path / "corrupt.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\nInvalid broken truncated binary garbage")

        result = scanner.scan_file(pdf_path)
        assert result.scan_successful is False
        assert result.is_sensitive is False
        assert result.error is not None

    def test_nonexistent_pdf(self, tmp_path, scanner):
        """Verify nonexistent PDF path returns scan_successful=False with clear error."""
        pdf_path = tmp_path / "missing.pdf"
        result = scanner.scan_file(pdf_path)
        assert result.scan_successful is False
        assert "File not found" in result.error
