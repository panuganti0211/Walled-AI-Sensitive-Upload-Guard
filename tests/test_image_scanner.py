"""Unit tests for the ImageScanner and local OCR preprocessing pipeline."""

from unittest.mock import patch
import pytest
from pathlib import Path
from PIL import Image, ImageDraw
import pytesseract

from app.scanner.image_scanner import ImageScanner


class TestImageScanner:
    """Test suite for ImageScanner."""

    @pytest.fixture
    def scanner(self):
        return ImageScanner()

    def _create_sample_image(self, tmp_path: Path, filename: str, text: str, mode: str = "RGB") -> Path:
        """Helper to create a test image containing rendered text."""
        img_path = tmp_path / filename
        img = Image.new(mode, (450, 120), color=(255, 255, 255) if mode == "RGB" else 255)
        draw = ImageDraw.Draw(img)
        draw.text((20, 40), text, fill=(0, 0, 0) if mode == "RGB" else 0)
        img.save(str(img_path))
        return img_path

    def test_image_preprocessing_rgba(self, tmp_path, scanner):
        """Verify RGBA transparency composite and grayscale conversion."""
        rgba_img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        preprocessed = scanner.preprocess_image(rgba_img)
        assert preprocessed.mode == "L"
        # Verify upscale of small image (original was 100x100, should be scaled up)
        assert preprocessed.size[0] >= 600

    def test_image_preprocessing_small_upscale(self, scanner):
        """Verify small images are scaled up to ensure OCR can distinguish characters."""
        small_img = Image.new("RGB", (200, 50), color="white")
        preprocessed = scanner.preprocess_image(small_img)
        assert preprocessed.size[0] >= 600

    def test_ocr_unavailable_fail_secure(self, tmp_path, scanner):
        """Verify that when OCR is unavailable, scan_successful=False and error is returned.

        DLP Rule: If content cannot be scanned, it must NOT be silently marked safe.
        """
        img_path = self._create_sample_image(tmp_path, "sample.png", "Sample text")

        with patch.object(scanner, "is_ocr_available", return_value=False):
            result = scanner.scan_file(img_path)
            assert result.scan_successful is False
            assert result.is_sensitive is False
            assert result.error is not None
            assert "Tesseract OCR engine is not installed" in result.error
            assert len(result.warnings) > 0

    def test_invalid_corrupted_image(self, tmp_path, scanner):
        """Verify an invalid/corrupted image file returns scan_successful=False."""
        bad_img = tmp_path / "broken.png"
        bad_img.write_bytes(b"\x89PNG\r\n\x1a\nCorrupted binary header data")

        result = scanner.scan_file(bad_img)
        assert result.scan_successful is False
        assert result.is_sensitive is False
        assert result.error is not None
        assert "Invalid or corrupted image" in result.error

    def test_nonexistent_image(self, tmp_path, scanner):
        """Verify nonexistent image path returns scan_successful=False."""
        missing = tmp_path / "missing.png"
        result = scanner.scan_file(missing)
        assert result.scan_successful is False
        assert "File not found" in result.error

    def test_ocr_detection_with_sensitive_marker(self, tmp_path, scanner):
        """Verify detection when OCR extracts text containing WALLED_SENSITIVE."""
        img_path = self._create_sample_image(tmp_path, "sensitive.png", "WALLED_SENSITIVE")

        with patch.object(scanner, "is_ocr_available", return_value=True), \
             patch("pytesseract.image_to_string", return_value="Invoice #123\nSecurity: WALLED_SENSITIVE\nApproved"):
            result = scanner.scan_file(img_path)
            assert result.scan_successful is True
            assert result.is_sensitive is True
            assert result.detected_marker == "WALLED_SENSITIVE"
            assert result.locations == ["image:ocr"]

    def test_ocr_detection_safe_image(self, tmp_path, scanner):
        """Verify safe image without marker returns is_sensitive=False."""
        img_path = self._create_sample_image(tmp_path, "safe.png", "Normal diagram")

        with patch.object(scanner, "is_ocr_available", return_value=True), \
             patch("pytesseract.image_to_string", return_value="Architecture Diagram: Component A to Component B"):
            result = scanner.scan_file(img_path)
            assert result.scan_successful is True
            assert result.is_sensitive is False
            assert result.detected_marker is None

    def test_ocr_empty_text_result(self, tmp_path, scanner):
        """Verify image with no readable text returns is_sensitive=False and scan_successful=True."""
        img_path = self._create_sample_image(tmp_path, "blank.png", "")

        with patch.object(scanner, "is_ocr_available", return_value=True), \
             patch("pytesseract.image_to_string", return_value="   \n\n  "):
            result = scanner.scan_file(img_path)
            assert result.scan_successful is True
            assert result.is_sensitive is False

    def test_tesseract_runtime_error_handling(self, tmp_path, scanner):
        """Verify runtime TesseractError is caught and returned as structured error."""
        img_path = self._create_sample_image(tmp_path, "test.png", "test")

        with patch.object(scanner, "is_ocr_available", return_value=True), \
             patch("pytesseract.image_to_string", side_effect=pytesseract.TesseractError(1, "OCR Crash")):
            result = scanner.scan_file(img_path)
            assert result.scan_successful is False
            assert result.is_sensitive is False
            assert "OCR processing failed" in result.error
