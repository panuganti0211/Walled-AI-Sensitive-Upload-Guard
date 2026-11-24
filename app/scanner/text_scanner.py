"""TXT file content scanner."""

import os
from pathlib import Path
from typing import List, Optional, Tuple, Union

from app.scanner.detector import MarkerDetector, default_detector
from app.scanner.models import ScanResult

# Encodings attempted in priority order
CANDIDATE_ENCODINGS = (
    "utf-8-sig",  # UTF-8 with BOM
    "utf-8",      # Standard UTF-8
    "utf-16",     # UTF-16 with BOM
    "utf-16-le",  # UTF-16 Little Endian without BOM
    "utf-16-be",  # UTF-16 Big Endian without BOM
    "cp1252",     # Windows Western European / ANSI
    "latin-1",    # Fallback byte-to-char mapping
)


class TextScanner:
    """Scans plain text files and raw text for sensitive markers."""

    def __init__(self, detector: Optional[MarkerDetector] = None):
        self.detector = detector or default_detector

    def scan_file(self, file_path: Union[str, Path]) -> ScanResult:
        """Scan a .txt file on disk.

        Handles multiple encodings, BOM markers, empty files, and permission errors safely.

        Args:
            file_path: Absolute or relative path to the text file.

        Returns:
            ScanResult containing detection state, decoded text summary, and any warnings/errors.
        """
        path = Path(file_path)

        if not path.exists():
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="txt",
                error=f"File not found: {path}",
            )

        if not path.is_file():
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="txt",
                error=f"Target is not a regular file: {path}",
            )

        try:
            raw_bytes = path.read_bytes()
        except Exception as e:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=str(path),
                file_type="txt",
                error=f"Failed to read file: {e}",
            )

        return self.scan_bytes(raw_bytes, file_path=str(path))

    def scan_bytes(self, raw_bytes: bytes, file_path: Optional[str] = None) -> ScanResult:
        """Scan raw bytes attempting multiple encodings."""
        if not raw_bytes:
            return ScanResult(
                is_sensitive=False,
                scan_successful=True,
                file_path=file_path,
                file_type="txt",
                extracted_text="",
            )

        decoded_text, encoding_used, warnings = self._decode_bytes(raw_bytes)

        if decoded_text is None:
            return ScanResult(
                is_sensitive=False,
                scan_successful=False,
                file_path=file_path,
                file_type="txt",
                error="Failed to decode text file with any supported encoding.",
                warnings=warnings,
            )

        detection = self.detector.detect(decoded_text)

        return ScanResult(
            is_sensitive=detection.found,
            scan_successful=True,
            file_path=file_path,
            file_type="txt",
            detected_marker=detection.marker if detection.found else None,
            locations=[f"matches:{detection.count}"] if detection.found else [],
            extracted_text=decoded_text[:1000],
            warnings=warnings,
        )

    def scan_text(self, text: str, source_label: str = "text") -> ScanResult:
        """Directly scan an already-decoded text string."""
        detection = self.detector.detect(text)
        return ScanResult(
            is_sensitive=detection.found,
            scan_successful=True,
            file_type="prompt" if source_label == "prompt" else "txt",
            detected_marker=detection.marker if detection.found else None,
            locations=[f"matches:{detection.count}"] if detection.found else [],
            extracted_text=text[:1000] if text else "",
        )

    def _decode_bytes(self, data: bytes) -> Tuple[Optional[str], Optional[str], List[str]]:
        """Attempt decoding with BOM-aware and candidate encodings in priority order."""
        warnings: List[str] = []

        # 1. Check for explicit Byte Order Marks (BOM)
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            try:
                decoded = data.decode("utf-16")
                warnings.append("Decoded using UTF-16 (BOM detected)")
                return decoded, "utf-16", warnings
            except UnicodeDecodeError:
                pass

        if data.startswith(b"\xef\xbb\xbf"):
            try:
                decoded = data.decode("utf-8-sig")
                return decoded, "utf-8-sig", warnings
            except UnicodeDecodeError:
                pass

        # 2. Try standard UTF-8 (covers modern text files)
        try:
            decoded = data.decode("utf-8")
            return decoded, "utf-8", warnings
        except UnicodeDecodeError:
            pass

        # 3. Try Windows Western European (CP1252) and Latin-1
        for enc in ("cp1252", "latin-1"):
            try:
                decoded = data.decode(enc)
                warnings.append(f"Decoded using fallback encoding: {enc}")
                return decoded, enc, warnings
            except (UnicodeDecodeError, LookupError):
                continue

        # 4. Fallback UTF-16 if data has an even length
        try:
            decoded = data.decode("utf-16")
            warnings.append("Decoded using fallback encoding: utf-16")
            return decoded, "utf-16", warnings
        except UnicodeDecodeError:
            pass

        # 5. Last resort: UTF-8 with replacement characters
        try:
            decoded = data.decode("utf-8", errors="replace")
            warnings.append("Decoded with replacement characters due to encoding errors")
            return decoded, "utf-8-replace", warnings
        except Exception as e:
            warnings.append(f"Decoding failed: {e}")
            return None, None, warnings
