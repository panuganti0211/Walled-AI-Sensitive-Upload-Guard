"""Target website detection and URL domain classification."""

from urllib.parse import urlparse
from typing import Optional


CHATGPT_DOMAINS = ("chatgpt.com", "chat.openai.com", "oaiusercontent.com", "openai.com")
PERPLEXITY_DOMAINS = ("perplexity.ai", "www.perplexity.ai")


def extract_domain(url: str) -> str:
    """Safely extract lowercase hostname from a URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""


def is_chatgpt_url(url: str) -> bool:
    """Check if the given URL belongs to ChatGPT."""
    domain = extract_domain(url)
    return any(domain == d or domain.endswith("." + d) for d in CHATGPT_DOMAINS)


def is_perplexity_url(url: str) -> bool:
    """Check if the given URL belongs to Perplexity."""
    domain = extract_domain(url)
    return any(domain == d or domain.endswith("." + d) for d in PERPLEXITY_DOMAINS)


def identify_platform(url: str) -> str:
    """Identify target platform name ('ChatGPT', 'Perplexity', or 'Unknown')."""
    if is_chatgpt_url(url):
        return "ChatGPT"
    elif is_perplexity_url(url):
        return "Perplexity"
    return "Unknown"
