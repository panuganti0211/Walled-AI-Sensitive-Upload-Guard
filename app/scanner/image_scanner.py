"""Local offline image content scanner using Pillow and pytesseract OCR."""

import os
import shutil
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image, ImageEnhance, ImageFilter, UnidentifiedImageError
import pytesseract

from app.scanner.detector import MarkerDetector, default_detector
from app.scanner.models import ScanResult

# Common default installation locations for Tesseract on Windows
WINDOWS_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]


class ImageScanner:
    """Scans image files (PNG, JPG, JPEG, WebP) for sensitive markers using local OCR."""

    def __init__(
        self,
        detector: Optional[MarkerDetector] = None,
        tesseract_cmd: Optional[str] = None,
    ):
        self.detector = detector or default_detector
        self._configure_tesseract(tesseract_cmd)

    def _configure_tesseract(self, explicit_path: Optional[str] = None) -> None:
        """Locate and configure the local Tesseract OCR binary."""
        if explicit_path and os.path.isfile(explicit_path):
            pytesseract.pytesseract.tesseract_cmd = explicit_path
            return

        # Check if already on system PATH
        if shutil.which("tesseract"):
            return

        # Check known Windows installation paths
        for candidate in WINDOWS_TESSERACT_PATHS:
            if os.path.isfile(candidate):
                pytesseract.pytesseract.tesseract_cmd = candidate
                return

    def is_ocr_available(self) -> bool:
        """Check whether the local Tesseract OCR engine is installed and executable."""
        cmd = pytesseract.pytesseract.tesseract_cmd
        if cmd and os.path.isfile(cmd):
            return True
        return shutil.which("tesseract") is not None

    def preprocess_image(self, img: Image.Image) -> Image.Image:
        """Preprocess image to maximize OCR accuracy for text recognition.

        Steps:
        1. Composite RGBA/palette with transparency onto a white background.
        2. Convert to grayscale.
        3. Upscale small images (LANCZOS) so character heights meet OCR thresholds.
        4. Enhance contrast.
        """
        # Handle transparency (RGBA / LA / P)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Convert to grayscale
        gray = img.convert("L")

        # Scale up small images for better OCR character recognition
        width, height = gray.size
        if width < 600 or height < 150:
            scale_factor = max(2, int(600 / max(width, 1)))
            new_size = (width * scale_factor, height * scale_factor)
            gray = gray.resize(new_size, Image.Resampling.LANCZOS)

        # Enhance contrast
        enhancer = ImageEnhance.Contrast(gray)
        enhanced = enhancer.enhance(1.8)

        return enhanced

    def scan_file(self, file_path: Union[str, Path]) -> ScanResult:
        """Scan an image file on disk.

        Args:
            file_path: Path to PNG, JPG, JPEG, or WebP image.

        Returns:
            ScanResult containing OCR detection outcome, error if unreadable, or missing OCR engine.
        """
        path = Path(file_path)

        if not path.exists():
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="image",
                error=f"File not found: {path}",
            )

        if not path.is_file():
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="image",
                error=f"Target is not a regular file: {path}",
            )

        try:
            with Image.open(str(path)) as img:
                return self.scan_image(img, file_path=str(path))
        except (UnidentifiedImageError, OSError) as e:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="image",
                error=f"Invalid or corrupted image format: {e}",
            )
        except Exception as e:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="image",
                error=f"Failed to open image file: {e}",
            )

    def scan_bytes(self, image_bytes: bytes, file_path: Optional[str] = None) -> ScanResult:
        """Scan image content provided directly as in-memory bytes (e.g. from upload streams)."""
        import io
        if not image_bytes:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="image",
                error="Image content is empty (0 bytes).",
            )
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                return self.scan_image(img, file_path=file_path)
        except (UnidentifiedImageError, OSError) as e:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="image",
                error=f"Invalid or corrupted image format: {e}",
            )
        except Exception as e:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="image",
                error=f"Failed to open image bytes: {e}",
            )

    def scan_image(self, img: Image.Image, file_path: Optional[str] = None) -> ScanResult:
        """Perform preprocessing and OCR scanning on a Pillow Image instance."""
        if not self.is_ocr_available():
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="image",
                error="Tesseract OCR engine is not installed or not found on PATH. "
                      "Image cannot be safely inspected offline.",
                warnings=["OCR unavailable: image scanning failed-secure."],
            )

        try:
            preprocessed = self.preprocess_image(img)
            # Run local offline OCR
            ocr_text = pytesseract.image_to_string(preprocessed)
        except pytesseract.TesseractNotFoundError:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="image",
                error="Tesseract OCR executable was not found.",
            )
        except Exception as e:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="image",
                error=f"OCR processing failed: {e}",
            )

        detection = self.detector.detect(ocr_text)

        return ScanResult(
            is_sensitive=detection.found,
            scan_successful=True,
            file_path=file_path,
            file_type="image",
            detected_marker=detection.marker if detection.found else None,
            locations=["image:ocr"] if detection.found else [],
            extracted_text=ocr_text[:500] if ocr_text else "",
        )
