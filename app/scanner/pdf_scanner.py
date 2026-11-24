"""PDF document content scanner using PyMuPDF (fitz)."""

from pathlib import Path
from typing import List, Optional, Union

import pymupdf  # PyMuPDF engine
fitz = pymupdf

from app.scanner.detector import MarkerDetector, default_detector
from app.scanner.models import ScanResult


class PDFScanner:
    """Scans all pages of PDF documents for sensitive markers using PyMuPDF."""

    def __init__(self, detector: Optional[MarkerDetector] = None):
        self.detector = detector or default_detector

    def scan_file(self, file_path: Union[str, Path]) -> ScanResult:
        """Scan a PDF file on disk across all pages.

        Args:
            file_path: Path to the PDF file.

        Returns:
            ScanResult detailing whether the marker was found and on which page numbers (1-indexed).
        """
        path = Path(file_path)

        if not path.exists():
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="pdf",
                error=f"File not found: {path}",
            )

        if not path.is_file():
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="pdf",
                error=f"Target is not a regular file: {path}",
            )

        try:
            doc = fitz.open(str(path))
        except Exception as e:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="pdf",
                error=f"Invalid or corrupted PDF file: {e}",
            )

        return self._scan_doc(doc, file_path=str(path))

    def scan_bytes(self, pdf_bytes: bytes, file_path: Optional[str] = None) -> ScanResult:
        """Scan PDF content provided as raw bytes."""
        if not pdf_bytes:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="pdf",
                error="PDF content is empty (0 bytes).",
            )

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="pdf",
                error=f"Failed to parse PDF bytes: {e}",
            )

        return self._scan_doc(doc, file_path=file_path)

    def _scan_doc(self, doc: fitz.Document, file_path: Optional[str] = None) -> ScanResult:
        """Iterate through all document pages and detect marker."""
        warnings: List[str] = []
        matching_pages: List[int] = []
        full_extracted_snippets: List[str] = []

        try:
            page_count = len(doc)
            if page_count == 0:
                warnings.append("PDF document has 0 pages.")
                return ScanResult(
                    is_sensitive=False,
                    scan_successful=True,
                    file_path=file_path,
                    file_type="pdf",
                    warnings=warnings,
                )

            for page_index in range(page_count):
                page_num = page_index + 1  # 1-indexed page number for human readability
                page = doc[page_index]
                text = page.get_text()

                if text:
                    detection = self.detector.detect(text)
                    if detection.found:
                        matching_pages.append(page_num)
                        full_extracted_snippets.append(f"[Page {page_num}]: {text[:200]}")

            is_sensitive = len(matching_pages) > 0
            snippet_summary = "\n".join(full_extracted_snippets)[:1000] if is_sensitive else ""

            return ScanResult(
                is_sensitive=is_sensitive,
                scan_successful=True,
                file_path=file_path,
                file_type="pdf",
                detected_marker=self.detector.marker if is_sensitive else None,
                locations=matching_pages,
                extracted_text=snippet_summary,
                warnings=warnings,
            )
        except Exception as e:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="pdf",
                error=f"Error occurred while scanning PDF pages: {e}",
                warnings=warnings,
            )
        finally:
            try:
                doc.close()
            except Exception:
                pass
