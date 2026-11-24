"""Unit tests for the centralized sensitive marker detector."""

import pytest

from app.scanner.detector import MarkerDetector, detect_marker


class TestMarkerDetector:
    """Test suite for MarkerDetector."""

    def test_exact_marker_found(self):
        """Verify exact marker match."""
        detector = MarkerDetector(marker="WALLED_SENSITIVE")
        result = detector.detect("WALLED_SENSITIVE")
        assert result.found is True
        assert result.count == 1
        assert result.marker == "WALLED_SENSITIVE"
        assert result.indices == [0]

    def test_marker_absent(self):
        """Verify clean text returns no detection."""
        detector = MarkerDetector()
        result = detector.detect("This is completely safe text for ChatGPT.")
        assert result.found is False
        assert result.count == 0
        assert result.indices == []
        assert detector.contains_marker("Safe text") is False

    def test_marker_embedded_in_words(self):
        """Verify detection when marker is surrounded by letters without whitespace."""
        detector = MarkerDetector()
        text = "PRE_WALLED_SENSITIVE_POST"
        result = detector.detect(text)
        assert result.found is True
        assert result.count == 1
        assert result.indices == [4]

    def test_marker_surrounded_by_punctuation(self):
        """Verify detection when enclosed in brackets, quotes, or trailing punctuation."""
        detector = MarkerDetector()
        sample = 'Warning: {"secret": "WALLED_SENSITIVE"}! Do not upload.'
        result = detector.detect(sample)
        assert result.found is True
        assert result.count == 1

    def test_marker_whitespace_variations(self):
        """Verify detection with tabs, newlines, and multiple spaces."""
        detector = MarkerDetector()
        sample = "Line 1\n\t  WALLED_SENSITIVE  \nLine 3"
        result = detector.detect(sample)
        assert result.found is True
        assert result.count == 1

    def test_multiple_marker_occurrences(self):
        """Verify detection of multiple occurrences in a single string."""
        detector = MarkerDetector()
        sample = "WALLED_SENSITIVE first and WALLED_SENSITIVE second"
        result = detector.detect(sample)
        assert result.found is True
        assert result.count == 2
        assert len(result.indices) == 2

    def test_empty_and_none_input(self):
        """Verify empty string and None input do not crash and return found=False."""
        detector = MarkerDetector()
        assert detector.detect("").found is False
        assert detector.detect(None).found is False

    def test_case_sensitivity_behavior_default(self):
        """Verify default behavior is case-sensitive (canonical WALLED_SENSITIVE).

        Documented behavior:
        By default, 'WALLED_SENSITIVE' is matched strictly in uppercase.
        Lowercase or mixed case ('walled_sensitive') is NOT matched by default
        to prevent false positives with loose phrasing.
        """
        detector = MarkerDetector(case_sensitive=True)
        assert detector.detect("WALLED_SENSITIVE").found is True
        assert detector.detect("walled_sensitive").found is False
        assert detector.detect("Walled_Sensitive").found is False

    def test_case_insensitive_behavior_override(self):
        """Verify case_sensitive=False enables matching of lowercase/mixed case."""
        detector = MarkerDetector(case_sensitive=False)
        assert detector.detect("walled_sensitive").found is True
        assert detector.detect("Walled_Sensitive").found is True
        assert detector.detect("WALLED_SENSITIVE").found is True

    def test_module_level_detect_marker_convenience_function(self):
        """Verify module-level detect_marker helper behaves identically."""
        assert detect_marker("WALLED_SENSITIVE").found is True
        assert detect_marker("Safe content").found is False
