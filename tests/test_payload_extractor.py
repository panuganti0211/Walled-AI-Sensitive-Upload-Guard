"""Unit tests for the CDP payload extractor."""

import json
from app.browser.payload_extractor import extract_multipart_files, extract_prompt_strings


class TestPayloadExtractor:
    """Test suite for extracting prompt strings and multipart upload files."""

    def test_extract_prompt_chatgpt_json_format(self):
        """Verify extraction from standard ChatGPT messages structure."""
        payload = json.dumps({
            "action": "next",
            "messages": [
                {
                    "id": "msg-1",
                    "author": {"role": "user"},
                    "content": {
                        "content_type": "text",
                        "parts": ["Please explain WALLED_SENSITIVE encryption."],
                    },
                }
            ],
            "model": "gpt-4o",
        })
        strings = extract_prompt_strings(payload)
        combined = " ".join(strings)
        assert "WALLED_SENSITIVE" in combined

    def test_extract_prompt_perplexity_json_format(self):
        """Verify extraction from Perplexity query structure."""
        payload = json.dumps({
            "query": "Is WALLED_SENSITIVE present in the code?",
            "mode": "concise",
            "search_focus": "internet",
        })
        strings = extract_prompt_strings(payload)
        combined = " ".join(strings)
        assert "WALLED_SENSITIVE" in combined

    def test_extract_prompt_url_encoded(self):
        """Verify extraction from URL-encoded form data."""
        payload = "action=search&q=Find+WALLED_SENSITIVE+documents&user=123"
        strings = extract_prompt_strings(payload)
        combined = " ".join(strings)
        assert "WALLED_SENSITIVE" in combined

    def test_extract_prompt_plain_text(self):
        """Verify raw plain-text payload extraction."""
        payload = "Direct prompt containing WALLED_SENSITIVE string"
        strings = extract_prompt_strings(payload)
        assert len(strings) == 1
        assert "WALLED_SENSITIVE" in strings[0]

    def test_extract_prompt_empty_and_none(self):
        """Verify empty and None payloads return empty list."""
        assert extract_prompt_strings("") == []
        assert extract_prompt_strings("   ") == []
        assert extract_prompt_strings(None) == []

    def test_extract_prompt_malformed_json_fallback(self):
        """Verify malformed JSON falls back gracefully to plain text without crashing."""
        broken_json = '{"query": "WALLED_SENSITIVE incomplete'
        strings = extract_prompt_strings(broken_json)
        assert len(strings) > 0
        assert "WALLED_SENSITIVE" in strings[0]

    def test_extract_multipart_txt_file(self):
        """Verify multipart/form-data extraction of a text file."""
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        raw_body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="report.txt"\r\n'
            f"Content-Type: text/plain\r\n\r\n"
            f"Confidential data: WALLED_SENSITIVE\r\n"
            f"--{boundary}--\r\n"
        )
        headers = {"content-type": f"multipart/form-data; boundary={boundary}"}
        parts = extract_multipart_files(raw_body, headers)

        assert len(parts) == 1
        assert parts[0].filename == "report.txt"
        assert b"WALLED_SENSITIVE" in parts[0].content_bytes

    def test_extract_multipart_missing_boundary(self):
        """Verify non-multipart payload returns empty list safely."""
        parts = extract_multipart_files("simple non-multipart text")
        assert parts == []
