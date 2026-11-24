"""Browser integration, CDP observation, and DLP enforcement package."""

from app.browser.browser_controller import BrowserController
from app.browser.browser_manager import BrowserManager
from app.browser.cdp_client import CDPClient
from app.browser.enforcement_manager import (
    BridgeFile,
    EnforcementManager,
    PausedRequest,
    RequestLifecycleState,
)
from app.browser.file_bridge import FileBridge
from app.browser.models import ApprovalDecision, BrowserStatus, CandidateRequest, CDPStatus
from app.browser.payload_extractor import (
    UploadedPart,
    extract_multipart_files,
    extract_prompt_strings,
)
from app.browser.request_classifier import classify_request
from app.browser.response_styler import ResponseStyler
from app.browser.site_detection import (
    identify_platform,
    is_chatgpt_url,
    is_perplexity_url,
)

__all__ = [
    "ApprovalDecision",
    "BrowserStatus",
    "CDPStatus",
    "CandidateRequest",
    "BrowserManager",
    "CDPClient",
    "BrowserController",
    "EnforcementManager",
    "FileBridge",
    "BridgeFile",
    "PausedRequest",
    "RequestLifecycleState",
    "ResponseStyler",
    "UploadedPart",
    "extract_prompt_strings",
    "extract_multipart_files",
    "classify_request",
    "is_chatgpt_url",
    "is_perplexity_url",
    "identify_platform",
]
