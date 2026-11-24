"""Sensitive marker detector.

Centralized detection logic for the predefined DLP marker: WALLED_SENSITIVE.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.config.settings import config


@dataclass
class DetectionResult:
    """Result of a text scan for sensitive markers."""

    found: bool = False
    marker: Optional[str] = None
    count: int = 0
    indices: List[int] = field(default_factory=list)


class MarkerDetector:
    """Detects the sensitive marker in arbitrary text strings."""

    def __init__(self, marker: Optional[str] = None, case_sensitive: bool = True):
        """Initialize the marker detector.

        Args:
            marker: The sensitive marker to detect. Defaults to config.sensitive_marker ('WALLED_SENSITIVE').
            case_sensitive: Whether detection requires exact case match (default True).
                            When False, matches case-insensitively ('walled_sensitive', etc.).
        """
        self.marker = marker or config.sensitive_marker
        self.case_sensitive = case_sensitive

    def detect(self, text: Optional[str]) -> DetectionResult:
        """Scan input text for occurrences of the sensitive marker.

        The marker is detected whether standalone, surrounded by whitespace,
        embedded within other words, or bordered by punctuation.

        Args:
            text: Arbitrary string to inspect.

        Returns:
            DetectionResult detailing whether the marker was found, the count, and byte/char indices.
        """
        if not text:
            return DetectionResult(found=False, marker=self.marker, count=0, indices=[])

        flags = 0 if self.case_sensitive else re.IGNORECASE
        escaped_marker = re.escape(self.marker)
        pattern = re.compile(escaped_marker, flags)

        matches = list(pattern.finditer(text))
        if not matches:
            return DetectionResult(found=False, marker=self.marker, count=0, indices=[])

        return DetectionResult(
            found=True,
            marker=self.marker,
            count=len(matches),
            indices=[m.start() for m in matches],
        )

    def contains_marker(self, text: Optional[str]) -> bool:
        """Convenience method returning True if marker is present in text."""
        return self.detect(text).found


# Default singleton detector instance
default_detector = MarkerDetector()


def detect_marker(text: Optional[str], marker: Optional[str] = None, case_sensitive: bool = True) -> DetectionResult:
    """Convenience function to detect sensitive marker in text."""
    detector = default_detector if (marker is None and case_sensitive is True) else MarkerDetector(marker, case_sensitive)
    return detector.detect(text)
