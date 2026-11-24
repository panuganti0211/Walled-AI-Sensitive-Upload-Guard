"""Data models and enumeration states for browser management and CDP integration."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BrowserStatus(str, Enum):
    """Runtime status of the managed browser process."""

    NOT_LAUNCHED = "Not Launched"
    STARTING = "Starting..."
    RUNNING = "Running"
    DISCONNECTED = "Disconnected"
    ERROR = "Error"


class ApprovalDecision(str, Enum):
    """User decision for intercepted sensitive content."""

    CANCEL = "cancel"
    CONTINUE = "continue"


class CDPStatus(str, Enum):
    """Connection state of the Chrome DevTools Protocol client."""

    DISCONNECTED = "Disconnected"
    CONNECTING = "Connecting..."
    CONNECTED = "Connected"


@dataclass
class CandidateRequest:
    """Safe metadata representation of an observed network request.

    STRICT DLP SECURITY RULE:
    Never store raw request bodies, user prompt text, uploaded file content,
    cookies, or authorization bearer tokens.
    """

    request_id: str
    platform: str  # "ChatGPT", "Perplexity", or "Unknown"
    request_type: str  # "prompt", "upload", "navigation", "other"
    method: str  # "POST", "GET", "PUT", etc.
    url: str
    path: str
    timestamp: str
    content_type: Optional[str] = None
    has_post_data: bool = False
    post_data_size: Optional[int] = None

    @property
    def is_candidate_prompt(self) -> bool:
        """True if this request matches prompt submission heuristics."""
        return self.request_type == "prompt"

    @property
    def is_candidate_upload(self) -> bool:
        """True if this request matches actual file-content transmission heuristics."""
        return self.request_type == "upload"

    @property
    def is_candidate_upload_init(self) -> bool:
        """True if this request is an upload initialization or metadata registration."""
        return self.request_type == "upload_init"
