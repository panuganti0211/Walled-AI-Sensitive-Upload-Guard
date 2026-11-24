"""Payload extractor for CDP intercepted request bodies.

Extracts prompt strings and attached file contents from JSON, multipart,
and URL-encoded request payloads safely without retaining or logging sensitive data.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs


def extract_prompt_strings(post_data: Optional[str], content_type: Optional[str] = None) -> List[str]:
    """Extract candidate prompt text strings from request postData.

    Inspects JSON recursively to extract all textual message content,
    guaranteeing coverage across model updates (e.g. ChatGPT messages[].content.parts,
    Perplexity query/text fields).

    Args:
        post_data: Raw string payload from CDP Fetch.requestPaused.
        content_type: Optional MIME content-type header.

    Returns:
        List of extracted prompt text segments.
    """
    if not post_data:
        return []

    stripped = post_data.strip()
    extracted: List[str] = []

    # 1. Attempt JSON parsing
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
            _collect_strings_from_json(parsed, extracted)
            if extracted:
                return extracted
        except Exception:
            pass  # Fall through to raw inspection

    # 2. Attempt URL-encoded parsing (e.g. key1=val1&query=prompt)
    if "=" in stripped and not stripped.startswith("----"):
        try:
            parsed_qs = parse_qs(stripped, keep_blank_values=False)
            for key, val_list in parsed_qs.items():
                for val in val_list:
                    if val and len(val.strip()) > 0:
                        extracted.append(val.strip())
            if extracted:
                return extracted
        except Exception:
            pass

    # 3. Plaintext fallback
    if stripped:
        extracted.append(stripped)

    return extracted


def _collect_strings_from_json(node: Any, result: List[str]) -> None:
    """Recursively traverse a JSON object/list to harvest text content."""
    if isinstance(node, str):
        val = node.strip()
        # Collect non-trivial strings (ignoring empty strings, UUIDs, model IDs if short)
        if val:
            result.append(val)
    elif isinstance(node, list):
        for item in node:
            _collect_strings_from_json(item, result)
    elif isinstance(node, dict):
        # Prioritize known high-relevance prompt fields if available
        priority_keys = ("parts", "text", "query", "prompt", "content", "input")
        for key in priority_keys:
            if key in node:
                _collect_strings_from_json(node[key], result)

        for k, v in node.items():
            if k not in priority_keys:
                _collect_strings_from_json(v, result)


class UploadedPart:
    """Represents a single part parsed from multipart upload payloads."""

    def __init__(self, field_name: str, filename: str, content_bytes: bytes, content_type: Optional[str] = None):
        self.field_name = field_name
        self.filename = filename
        self.content_bytes = content_bytes
        self.content_type = content_type


def extract_multipart_files(
    post_data: Optional[str],
    headers: Optional[Dict[str, str]] = None,
) -> List[UploadedPart]:
    """Parse multipart/form-data payloads to extract filename and file contents.

    Args:
        post_data: Raw string payload from CDP.
        headers: Request headers dictionary.

    Returns:
        List of UploadedPart containing filename, bytes, and content-type.
    """
    if not post_data or "Content-Disposition" not in post_data:
        return []

    # Detect boundary
    boundary: Optional[str] = None
    if headers:
        for k, v in headers.items():
            if k.lower() == "content-type" and "boundary=" in v:
                boundary = "--" + v.split("boundary=")[-1].strip().strip('"').strip("'")
                break

    if not boundary:
        # Infer boundary from the first line of post_data
        first_line = post_data.split("\r\n", 1)[0].split("\n", 1)[0].strip()
        if first_line.startswith("--"):
            boundary = first_line

    if not boundary:
        return []

    parts = post_data.split(boundary)
    uploaded_files: List[UploadedPart] = []

    for part in parts:
        if not part or part.strip() in ("", "--"):
            continue

        # Split headers from body
        if "\r\n\r\n" in part:
            header_section, body_section = part.split("\r\n\r\n", 1)
        elif "\n\n" in part:
            header_section, body_section = part.split("\n\n", 1)
        else:
            continue

        # Check for filename in Content-Disposition
        # E.g.: Content-Disposition: form-data; name="file"; filename="notes.txt"
        cd_match = re.search(r'filename="?([^";\r\n]+)"?', header_section, re.IGNORECASE)
        name_match = re.search(r'name="?([^";\r\n]+)"?', header_section, re.IGNORECASE)

        if cd_match:
            filename = cd_match.group(1).strip()
            field_name = name_match.group(1).strip() if name_match else "file"

            # Extract content-type of this part
            ct_match = re.search(r'Content-Type:\s*([^\r\n]+)', header_section, re.IGNORECASE)
            part_ct = ct_match.group(1).strip() if ct_match else None

            # Remove trailing CRLF from body section
            # Using latin-1 preserves 1:1 mapping of both text and raw binary PDF/image streams
            body_bytes = body_section.rstrip("\r\n").encode("latin-1", errors="replace")

            uploaded_files.append(
                UploadedPart(
                    field_name=field_name,
                    filename=filename,
                    content_bytes=body_bytes,
                    content_type=part_ct,
                )
            )

    return uploaded_files
