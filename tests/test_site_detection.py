"""Unit tests for target website detection and URL domain identification."""

from app.browser.site_detection import (
    extract_domain,
    identify_platform,
    is_chatgpt_url,
    is_perplexity_url,
)


def test_extract_domain():
    assert extract_domain("https://chatgpt.com/c/123") == "chatgpt.com"
    assert extract_domain("https://WWW.PERPLEXITY.AI/search?q=test") == "www.perplexity.ai"
    assert extract_domain("http://subdomain.chat.openai.com/") == "subdomain.chat.openai.com"
    assert extract_domain("") == ""
    assert extract_domain("invalid-url") == ""


def test_is_chatgpt_url():
    assert is_chatgpt_url("https://chatgpt.com") is True
    assert is_chatgpt_url("https://chatgpt.com/chat") is True
    assert is_chatgpt_url("https://chat.openai.com/backend-api/conversation") is True
    assert is_chatgpt_url("https://www.perplexity.ai") is False
    assert is_chatgpt_url("https://google.com") is False
    assert is_chatgpt_url("") is False


def test_is_perplexity_url():
    assert is_perplexity_url("https://www.perplexity.ai") is True
    assert is_perplexity_url("https://perplexity.ai/search/456") is True
    assert is_perplexity_url("https://chatgpt.com") is False
    assert is_perplexity_url("https://github.com") is False
    assert is_perplexity_url("") is False


def test_identify_platform():
    assert identify_platform("https://chatgpt.com/backend-api/conversation") == "ChatGPT"
    assert identify_platform("https://chat.openai.com/") == "ChatGPT"
    assert identify_platform("https://www.perplexity.ai/api/predict") == "Perplexity"
    assert identify_platform("https://perplexity.ai") == "Perplexity"
    assert identify_platform("https://wikipedia.org") == "Unknown"
