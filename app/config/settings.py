"""Application configuration and default settings."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class AppConfig:
    """Centralized configuration for Walled AI Sensitive Upload Guard."""

    app_name: str = "Walled AI Sensitive Upload Guard"
    version: str = "0.1.0"

    # Predefined sensitive marker
    sensitive_marker: str = "WALLED_SENSITIVE"

    # Target monitored domains
    target_domains: List[str] = field(
        default_factory=lambda: [
            "chatgpt.com",
            "www.perplexity.ai",
            "perplexity.ai",
        ]
    )

    # Monitored full URLs
    target_urls: List[str] = field(
        default_factory=lambda: [
            "https://chatgpt.com",
            "https://www.perplexity.ai",
        ]
    )

    # Supported file extensions for DLP scanning
    supported_file_extensions: List[str] = field(
        default_factory=lambda: [
            ".txt",
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        ]
    )

    # Configurable AI response styling color (CSS color / hex)
    ai_response_color: str = "#2563EB"  # Professional DLP blue highlight


config = AppConfig()
