"""Data models for sensitive content scanning and inspection results."""

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class ScanResult:
    """Represents the standardized outcome of a DLP content scan."""

    # True if the sensitive marker was detected
    is_sensitive: bool = False

    # True if the file/content was successfully parsed and inspected
    # False if an error occurred (e.g. unreadable, corrupt, missing OCR engine)
    scan_successful: bool = True

    # Path to the scanned file (if applicable)
    file_path: Optional[str] = None

    # Content category ("txt", "pdf", "image", "prompt", "unsupported")
    file_type: str = "unknown"

    # The exact marker detected (e.g. "WALLED_SENSITIVE") or None
    detected_marker: Optional[str] = None

    # Locations where the marker was found (e.g. [1, 3] for PDF page numbers)
    locations: List[Any] = field(default_factory=list)

    # Optional internal extracted text (or snippet) for inspection/debugging
    extracted_text: Optional[str] = None

    # Non-fatal warnings encountered during scan (e.g. encoding fallback)
    warnings: List[str] = field(default_factory=list)

    # Fatal or blocking error preventing complete scan
    error: Optional[str] = None

    @property
    def has_error(self) -> bool:
        """Helper to quickly check if scanning failed due to an error."""
        return self.error is not None or not self.scan_successful
