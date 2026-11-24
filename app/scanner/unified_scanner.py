"""Unified scanner interface.

Dispatches content to the appropriate specialized scanner based on file extension
or inspects user prompts directly.
"""

from pathlib import Path
from typing import Optional, Union

from app.config.settings import config
from app.scanner.detector import MarkerDetector, default_detector
from app.scanner.image_scanner import ImageScanner
from app.scanner.models import ScanResult
from app.scanner.pdf_scanner import PDFScanner
from app.scanner.text_scanner import TextScanner


class UnifiedScanner:
    """Unified entry point for scanning text, prompts, and file uploads."""

    def __init__(self, detector: Optional[MarkerDetector] = None):
        self.detector = detector or default_detector
        self.text_scanner = TextScanner(self.detector)
        self.pdf_scanner = PDFScanner(self.detector)
        self.image_scanner = ImageScanner(self.detector)

    def scan_file(self, file_path: Union[str, Path]) -> ScanResult:
        """Inspect a file by routing it to the appropriate format scanner.

        Supported types:
        - .txt: TextScanner
        - .pdf: PDFScanner
        - .png, .jpg, .jpeg, .webp: ImageScanner

        Args:
            file_path: Path to the target file.

        Returns:
            Standardized ScanResult. If the file format is unsupported,
            returns scan_successful=False with an explicit error.
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        if ext == ".txt":
            return self.text_scanner.scan_file(path)
        elif ext == ".pdf":
            return self.pdf_scanner.scan_file(path)
        elif ext in (".png", ".jpg", ".jpeg", ".webp"):
            return self.image_scanner.scan_file(path)
        else:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type=ext.lstrip(".") or "unknown",
                error=f"Unsupported file format: '{ext}' (Fail-Secure Policy). "
                      f"Supported formats: {config.supported_file_extensions}",
            )

    def scan_bytes(self, content_bytes: bytes, filename: str) -> ScanResult:
        """Inspect in-memory file bytes by routing to the appropriate format scanner.

        Supported types:
        - .txt: TextScanner
        - .pdf: PDFScanner
        - .png, .jpg, .jpeg, .webp: ImageScanner

        Args:
            content_bytes: Raw binary bytes of the file.
            filename: Target filename used for extension resolution.

        Returns:
            Standardized ScanResult.
        """
        ext = ("." + filename.split(".")[-1].lower()) if "." in filename else ""
        if ext == ".txt":
            return self.text_scanner.scan_bytes(content_bytes, file_path=filename)
        elif ext == ".pdf":
            return self.pdf_scanner.scan_bytes(content_bytes, file_path=filename)
        elif ext in (".png", ".jpg", ".jpeg", ".webp"):
            return self.image_scanner.scan_bytes(content_bytes, file_path=filename)
        else:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=filename,
                file_type=ext.lstrip(".") or "unknown",
                error=f"Unsupported file format: '{ext}' (Fail-Secure Policy). "
                      f"Supported formats: {config.supported_file_extensions}",
            )

    def scan_prompt(self, prompt_text: str) -> ScanResult:
        """Inspect user prompt text before outgoing submission."""
        return self.text_scanner.scan_text(prompt_text, source_label="prompt")


# Singleton instance for general use
default_unified_scanner = UnifiedScanner()


def scan_file(file_path: Union[str, Path]) -> ScanResult:
    """Scan a file using the default UnifiedScanner."""
    return default_unified_scanner.scan_file(file_path)


def scan_bytes(content_bytes: bytes, filename: str) -> ScanResult:
    """Scan in-memory file bytes using the default UnifiedScanner."""
    return default_unified_scanner.scan_bytes(content_bytes, filename)


def scan_prompt(prompt_text: str) -> ScanResult:
    """Scan a prompt string using the default UnifiedScanner."""
    return default_unified_scanner.scan_prompt(prompt_text)
