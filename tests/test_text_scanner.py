"""Unit tests for the TXT file content scanner."""

import pytest
from pathlib import Path

from app.scanner.text_scanner import TextScanner


class TestTextScanner:
    """Test suite for TextScanner."""

    @pytest.fixture
    def scanner(self):
        return TextScanner()

    def test_safe_txt_file(self, tmp_path, scanner):
        """Verify normal text without marker is safe."""
        file_path = tmp_path / "safe.txt"
        file_path.write_text("Hello, this is a harmless research query for ChatGPT.", encoding="utf-8")

        result = scanner.scan_file(file_path)
        assert result.scan_successful is True
        assert result.is_sensitive is False
        assert result.file_type == "txt"
        assert result.detected_marker is None
        assert result.error is None

    def test_sensitive_txt_file(self, tmp_path, scanner):
        """Verify text containing WALLED_SENSITIVE triggers sensitivity flag."""
        file_path = tmp_path / "confidential.txt"
        file_path.write_text(
            "Internal project notes: do not disclose. Marker: WALLED_SENSITIVE attached.",
            encoding="utf-8",
        )

        result = scanner.scan_file(file_path)
        assert result.scan_successful is True
        assert result.is_sensitive is True
        assert result.detected_marker == "WALLED_SENSITIVE"
        assert len(result.locations) > 0

    def test_utf8_bom_encoding(self, tmp_path, scanner):
        """Verify file saved with UTF-8 BOM is decoded properly and detected."""
        file_path = tmp_path / "bom.txt"
        file_path.write_text("Header\nWALLED_SENSITIVE with BOM\nFooter", encoding="utf-8-sig")

        result = scanner.scan_file(file_path)
        assert result.scan_successful is True
        assert result.is_sensitive is True

    def test_utf16_le_encoding(self, tmp_path, scanner):
        """Verify UTF-16 Little Endian encoding is parsed and detected."""
        file_path = tmp_path / "utf16le.txt"
        file_path.write_text("Sensitive content: WALLED_SENSITIVE", encoding="utf-16")

        result = scanner.scan_file(file_path)
        assert result.scan_successful is True
        assert result.is_sensitive is True

    def test_windows_cp1252_encoding(self, tmp_path, scanner):
        """Verify Windows CP1252 / ANSI encoded files are supported."""
        file_path = tmp_path / "ansi.txt"
        content = "Résumé with € symbol and WALLED_SENSITIVE marker."
        file_path.write_bytes(content.encode("cp1252"))

        result = scanner.scan_file(file_path)
        assert result.scan_successful is True
        assert result.is_sensitive is True

    def test_latin1_encoding(self, tmp_path, scanner):
        """Verify ISO-8859-1 (Latin-1) encoded files are supported."""
        file_path = tmp_path / "latin1.txt"
        content = "Café au lait and WALLED_SENSITIVE."
        file_path.write_bytes(content.encode("latin-1"))

        result = scanner.scan_file(file_path)
        assert result.scan_successful is True
        assert result.is_sensitive is True

    def test_empty_txt_file(self, tmp_path, scanner):
        """Verify empty (0 byte) file is handled safely without crashing."""
        file_path = tmp_path / "empty.txt"
        file_path.write_bytes(b"")

        result = scanner.scan_file(file_path)
        assert result.scan_successful is True
        assert result.is_sensitive is False
        assert result.extracted_text == ""

    def test_nonexistent_file(self, tmp_path, scanner):
        """Verify attempting to scan a nonexistent file returns scan_successful=False."""
        file_path = tmp_path / "does_not_exist.txt"

        result = scanner.scan_file(file_path)
        assert result.scan_successful is False
        assert result.is_sensitive is False
        assert result.error is not None
        assert "File not found" in result.error

    def test_scan_text_direct(self, scanner):
        """Verify direct text string scanning for prompt inspection."""
        res_safe = scanner.scan_text("Explain quantum computing", source_label="prompt")
        assert res_safe.scan_successful is True
        assert res_safe.is_sensitive is False
        assert res_safe.file_type == "prompt"

        res_sens = scanner.scan_text("Here is WALLED_SENSITIVE code", source_label="prompt")
        assert res_sens.scan_successful is True
        assert res_sens.is_sensitive is True
        assert res_sens.detected_marker == "WALLED_SENSITIVE"
