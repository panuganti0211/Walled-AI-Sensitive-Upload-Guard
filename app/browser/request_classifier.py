"""Classification of observed network requests for ChatGPT and Perplexity.

Identifies candidate prompt submissions and candidate file uploads based on
protocol methods, target endpoints, and MIME types.
"""

from datetime import datetime
from urllib.parse import urlparse
from typing import Dict, Optional

from app.browser.models import CandidateRequest
from app.browser.site_detection import extract_domain, identify_platform


# Endpoints and keywords indicating candidate prompt submission
CHATGPT_PROMPT_PATH_PATTERNS = (
    "/backend-api/conversation",
    "/backend-api/lat/r",
    "/backend-api/synthesize",
    "/conversation",
)

PERPLEXITY_PROMPT_PATH_PATTERNS = (
    "/api/predict",
    "/api/query",
    "/rest/query",
    "/socket.io",
    "/api/graphql",
    "/rest/perplexity_ask",
    "/rest/sse/perplexity_ask",
)

# Storage endpoints and CDN hosts receiving actual uploaded file bytes
STORAGE_UPLOAD_TARGETS = (
    "files.oaiusercontent.com",
    "oaiusercontent.com",
    "storage.googleapis.com",
    "blob.core.windows.net",
    "s3.amazonaws.com",
)

# Endpoints where upload sessions or metadata are initialized (prior to actual byte transmission)
UPLOAD_INIT_PATH_PATTERNS = (
    "/backend-api/files",
)

# Generic upload endpoints (may be actual upload or init depending on payload)
GENERIC_UPLOAD_PATH_PATTERNS = (
    "/api/upload",
    "/upload",
)

UPLOAD_PATH_PATTERNS = STORAGE_UPLOAD_TARGETS + UPLOAD_INIT_PATH_PATTERNS + GENERIC_UPLOAD_PATH_PATTERNS

STATIC_ASSET_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".ico",
)


def classify_request(
    url: str,
    method: str,
    headers: Optional[Dict[str, str]] = None,
    has_post_data: bool = False,
    post_data_size: Optional[int] = None,
    request_id: str = "",
    timestamp: Optional[str] = None,
) -> CandidateRequest:
    """Classify an observed network request into prompt, upload, navigation, or other.

    Args:
        url: Full request target URL.
        method: HTTP method (GET, POST, PUT, OPTIONS, etc.).
        headers: Dictionary of request headers (safe headers only).
        has_post_data: Whether a request body is present.
        post_data_size: Optional byte length of request body.
        request_id: Unique CDP network request identifier.
        timestamp: Formatted timestamp string.

    Returns:
        CandidateRequest object with safe metadata.
    """
    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    platform = identify_platform(url)
    method_upper = (method or "GET").upper()

    try:
        parsed = urlparse(url)
        path = parsed.path.lower()
    except Exception:
        path = ""

    # Normalize content-type header
    content_type = ""
    if headers:
        for k, v in headers.items():
            if k.lower() == "content-type":
                content_type = v.lower()
                break

    request_type = _determine_request_type(
        platform=platform,
        method=method_upper,
        path=path,
        url=url,
        content_type=content_type,
        has_post_data=has_post_data,
    )

    return CandidateRequest(
        request_id=request_id or "req-" + ts.replace(" ", "-"),
        platform=platform,
        request_type=request_type,
        method=method_upper,
        url=url,
        path=path,
        timestamp=ts,
        content_type=content_type or None,
        has_post_data=has_post_data,
        post_data_size=post_data_size,
    )


def _determine_request_type(
    platform: str,
    method: str,
    path: str,
    url: str,
    content_type: str,
    has_post_data: bool,
) -> str:
    """Determine request classification category."""
    # 1. Ignore static assets
    if any(path.endswith(ext) for ext in STATIC_ASSET_EXTENSIONS):
        return "other"

    # 2. Check File Upload candidates (POST/PUT)
    if method in ("POST", "PUT"):
        domain = extract_domain(url)
        is_oai_storage = domain == "oaiusercontent.com" or domain.endswith(".oaiusercontent.com")
        is_cloud_storage = any(
            domain == t or domain.endswith("." + t) or t in url.lower()
            for t in STORAGE_UPLOAD_TARGETS
        )
        # Actual storage upload: Any PUT or POST to storage host receiving file bytes
        is_storage_upload = is_oai_storage or is_cloud_storage

        is_multipart = "multipart/form-data" in content_type
        is_binary_payload = any(t in content_type for t in ("application/pdf", "image/", "application/octet-stream"))
        is_upload_init_path = any(p in path or p in url for p in UPLOAD_INIT_PATH_PATTERNS)
        has_generic_upload_path = any(p in path or p in url for p in GENERIC_UPLOAD_PATH_PATTERNS)

        # A. Actual File-Content Transmission:
        # - Direct storage upload (presigned PUT/POST to storage hosts)
        # - Any request carrying multipart form-data (contains actual file parts)
        # - Any request carrying binary file content (PDF, image, octet-stream)
        if is_storage_upload or is_multipart or is_binary_payload:
            return "upload"

        # B. Upload Metadata / Session Initialization:
        # - Endpoints like /backend-api/files with JSON metadata or empty body (session init)
        # - Generic upload path with explicit JSON metadata
        if is_upload_init_path:
            return "upload_init"

        if has_generic_upload_path and ("json" in content_type or not has_post_data):
            return "upload_init"

        if has_generic_upload_path:
            return "upload"

    # 3. Check Prompt submission candidates
    if method == "POST" and platform in ("ChatGPT", "Perplexity"):
        if platform == "ChatGPT":
            if any(p in path for p in CHATGPT_PROMPT_PATH_PATTERNS):
                return "prompt"
            # Generic POST on ChatGPT backend with JSON
            if "/backend-api/" in path and ("json" in content_type or has_post_data):
                return "prompt"

        elif platform == "Perplexity":
            if any(p in path for p in PERPLEXITY_PROMPT_PATH_PATTERNS):
                return "prompt"
            if "/api/" in path and ("json" in content_type or has_post_data):
                return "prompt"

    # 4. Check Navigation
    if method == "GET" and ("text/html" in content_type or path in ("", "/", "/chat")):
        return "navigation"

    return "other"
