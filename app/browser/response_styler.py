"""AI-generated response text color styler for ChatGPT and Perplexity.

Injects non-invasive CSS and a DOM MutationObserver via Chrome DevTools Protocol
(CDP) to colorize assistant/AI response text while strictly leaving user prompts,
buttons, sidebars, navigation, and code syntax intact.
"""

from typing import List, Optional

from app.config.settings import config


# Target selectors for AI-generated assistant text on ChatGPT
CHATGPT_ASSISTANT_SELECTORS: List[str] = [
    '[data-message-author-role="assistant"] .markdown p',
    '[data-message-author-role="assistant"] .markdown li',
    '[data-message-author-role="assistant"] .markdown h1',
    '[data-message-author-role="assistant"] .markdown h2',
    '[data-message-author-role="assistant"] .markdown h3',
    '[data-message-author-role="assistant"] .markdown blockquote',
    '[data-message-author-role="assistant"] .prose p',
    '[data-message-author-role="assistant"] .prose li',
    '.agent-turn .markdown p',
    '.agent-turn .markdown li',
]

# Target selectors for AI-generated answer text on Perplexity
PERPLEXITY_ANSWER_SELECTORS: List[str] = [
    'div[class*="prose"] p',
    'div[class*="prose"] li',
    'div[class*="prose"] h1',
    'div[class*="prose"] h2',
    'div[class*="prose"] h3',
    'div[class*="prose"] blockquote',
    '[data-testid="answer-text"] p',
    '[data-testid="answer-text"] li',
]

# Prohibited selectors that must NEVER receive the AI highlight color
PROHIBITED_USER_SELECTORS: List[str] = [
    '[data-message-author-role="user"]',
    '.user-turn',
    'textarea',
    'input',
    'button',
    'nav',
    'aside',
    'header',
]

STYLE_ELEMENT_ID = "walled-ai-response-styler"


class ResponseStyler:
    """Generates and manages CSS and JS injection payloads for AI response styling."""

    def __init__(self, color: Optional[str] = None):
        self._color = color or config.ai_response_color

    @property
    def color(self) -> str:
        return self._color

    @color.setter
    def color(self, value: str) -> None:
        self._color = value

    def generate_css(self) -> str:
        """Generate scoped CSS rules that apply the highlight color to AI responses."""
        all_selectors = CHATGPT_ASSISTANT_SELECTORS + PERPLEXITY_ANSWER_SELECTORS
        selector_chain = ",\n".join(all_selectors)

        css = (
            f"/* Walled AI Sensitive Upload Guard - AI Response Styling */\n"
            f"{selector_chain} {{\n"
            f"    color: {self._color} !important;\n"
            f"}}\n\n"
            f"/* Preserve code block font colors inside assistant messages */\n"
            f'[data-message-author-role="assistant"] pre code,\n'
            f'div[class*="prose"] pre code {{\n'
            f"    color: inherit;\n"
            f"}}\n"
        )
        return css

    def generate_injection_script(self) -> str:
        """Generate JavaScript that creates a persistent style element and MutationObserver.

        The script executes on page load and during streaming token generation,
        re-applying the styles dynamically if the SPA re-renders the DOM.
        """
        raw_css = self.generate_css().replace("\n", " ").replace('"', '\\"')

        js = f"""(function() {{
    const STYLE_ID = '{STYLE_ELEMENT_ID}';
    const CSS_CONTENT = "{raw_css}";

    // Only apply on ChatGPT and Perplexity domains
    const host = window.location.hostname || '';
    const isTarget = host.includes('chatgpt.com') || host.includes('perplexity.ai');
    if (!isTarget) return;

    function ensureStyleElement() {{
        let existing = document.getElementById(STYLE_ID);
        if (!existing) {{
            existing = document.createElement('style');
            existing.id = STYLE_ID;
            existing.type = 'text/css';
            existing.textContent = CSS_CONTENT;
            const target = document.head || document.documentElement;
            if (target) {{
                target.appendChild(existing);
            }}
        }} else if (existing.textContent !== CSS_CONTENT) {{
            existing.textContent = CSS_CONTENT;
        }}
    }}

    // Initial injection
    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', ensureStyleElement);
    }} else {{
        ensureStyleElement();
    }}

    // Watch for dynamic DOM re-renders and streaming answer tokens
    if (window.MutationObserver) {{
        const observer = new MutationObserver(function() {{
            ensureStyleElement();
        }});
        observer.observe(document.documentElement, {{
            childList: true,
            subtree: true
        }});
    }}
}})();"""
        return js

    def get_cdp_add_script_params(self) -> dict:
        """Return parameters for CDP Page.addScriptToEvaluateOnNewDocument."""
        return {"source": self.generate_injection_script()}

    def get_cdp_evaluate_params(self) -> dict:
        """Return parameters for CDP Runtime.evaluate."""
        return {
            "expression": self.generate_injection_script(),
            "returnByValue": True,
        }
