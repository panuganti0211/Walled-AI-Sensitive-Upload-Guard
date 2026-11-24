"""Sensitive content scanner package.

Provides modular and offline scanning for text, PDF, and image uploads.
"""

from app.scanner.detector import (
    DetectionResult,
    MarkerDetector,
    default_detector,
    detect_marker,
)
from app.scanner.image_scanner import ImageScanner
from app.scanner.models import ScanResult
from app.scanner.pdf_scanner import PDFScanner
from app.scanner.text_scanner import TextScanner
from app.scanner.unified_scanner import (
    UnifiedScanner,
    default_unified_scanner,
    scan_file,
    scan_prompt,
)

__all__ = [
    "ScanResult",
    "DetectionResult",
    "MarkerDetector",
    "default_detector",
    "detect_marker",
    "TextScanner",
    "PDFScanner",
    "ImageScanner",
    "UnifiedScanner",
    "default_unified_scanner",
    "scan_file",
    "scan_prompt",
]
