"""Unit tests for candidate request observation and classification."""

from app.browser.request_classifier import classify_request


class TestRequestClassifier:
    """Test suite for safe network request classification."""

    def test_classify_chatgpt_prompt_candidate(self):
        """Verify ChatGPT prompt conversation POST is classified as prompt."""
        candidate = classify_request(
            url="https://chatgpt.com/backend-api/conversation",
            method="POST",
            headers={"Content-Type": "application/json"},
            has_post_data=True,
            request_id="req-cg-1",
        )
        assert candidate.platform == "ChatGPT"
        assert candidate.request_type == "prompt"
        assert candidate.is_candidate_prompt is True
        assert candidate.is_candidate_upload is False
        assert candidate.method == "POST"

    def test_classify_chatgpt_upload_candidate(self):
        """Verify ChatGPT file upload request is classified as upload."""
        candidate = classify_request(
            url="https://chatgpt.com/backend-api/files",
            method="POST",
            headers={"Content-Type": "multipart/form-data; boundary=----WebKitFormBoundary"},
            has_post_data=True,
            request_id="req-cg-upload-1",
        )
        assert candidate.platform == "ChatGPT"
        assert candidate.request_type == "upload"
        assert candidate.is_candidate_upload is True
        assert candidate.is_candidate_prompt is False

    def test_classify_perplexity_prompt_candidate(self):
        """Verify Perplexity query POST is classified as prompt."""
        candidate = classify_request(
            url="https://www.perplexity.ai/api/predict",
            method="POST",
            headers={"Content-Type": "application/json"},
            has_post_data=True,
            request_id="req-perp-1",
        )
        assert candidate.platform == "Perplexity"
        assert candidate.request_type == "prompt"
        assert candidate.is_candidate_prompt is True

    def test_classify_perplexity_upload_candidate(self):
        """Verify Perplexity attachment upload is classified as upload."""
        candidate = classify_request(
            url="https://www.perplexity.ai/api/upload",
            method="POST",
            headers={"Content-Type": "multipart/form-data"},
            has_post_data=True,
            request_id="req-perp-upload-1",
        )
        assert candidate.platform == "Perplexity"
        assert candidate.request_type == "upload"
        assert candidate.is_candidate_upload is True

    def test_classify_static_assets_as_other(self):
        """Verify static scripts, styles, and images are classified as other."""
        css_req = classify_request("https://chatgpt.com/_next/static/css/app.css", method="GET")
        js_req = classify_request("https://www.perplexity.ai/main.js", method="GET")
        svg_req = classify_request("https://chatgpt.com/logo.svg", method="GET")

        assert css_req.request_type == "other"
        assert js_req.request_type == "other"
        assert svg_req.request_type == "other"

    def test_classify_navigation_request(self):
        """Verify top-level GET navigation requests are classified as navigation."""
        nav_req = classify_request(
            url="https://chatgpt.com/",
            method="GET",
            headers={"Content-Type": "text/html; charset=utf-8"},
        )
        assert nav_req.request_type == "navigation"

    def test_strict_security_no_body_content_stored(self):
        """Verify CandidateRequest contains only safe metadata and no sensitive payload."""
        candidate = classify_request(
            url="https://chatgpt.com/backend-api/conversation",
            method="POST",
            headers={"Authorization": "Bearer secret_token_12345", "Content-Type": "application/json"},
            has_post_data=True,
            request_id="req-safe-check",
        )
        # Verify no token or body was stored in candidate object
        candidate_dict = candidate.__dict__
        assert "Authorization" not in str(candidate_dict)
        assert "secret_token" not in str(candidate_dict)

    def test_classify_perplexity_sse_prompt_candidate(self):
        """Verify Perplexity SSE streaming inference POST is classified as prompt."""
        candidate = classify_request(
            url="https://www.perplexity.ai/rest/sse/perplexity_ask",
            method="POST",
            headers={"Content-Type": "application/json"},
            has_post_data=True,
            request_id="req-perp-sse-1",
        )
        assert candidate.platform == "Perplexity"
        assert candidate.request_type == "prompt"
        assert candidate.is_candidate_prompt is True
        assert candidate.is_candidate_upload is False

    def test_classify_perplexity_graphql_prompt_candidate(self):
        """Verify modern Perplexity GraphQL query POST is classified as prompt."""
        candidate = classify_request(
            url="https://www.perplexity.ai/rest/perplexity_ask/graphql",
            method="POST",
            headers={"Content-Type": "application/json"},
            has_post_data=True,
            request_id="req-perp-gql-1",
        )
        assert candidate.platform == "Perplexity"
        assert candidate.request_type == "prompt"
        assert candidate.is_candidate_prompt is True
        assert candidate.is_candidate_upload is False

    def test_classify_perplexity_telemetry_not_prompt(self):
        """Verify Perplexity analytics/telemetry POST is not classified as prompt."""
        candidate = classify_request(
            url="https://www.perplexity.ai/rest/event/analytics",
            method="POST",
            headers={"Content-Type": "application/json"},
            has_post_data=True,
            request_id="req-perp-telemetry-1",
        )
        assert candidate.platform == "Perplexity"
        assert candidate.request_type == "other"
        assert candidate.is_candidate_prompt is False
        assert candidate.is_candidate_upload is False
