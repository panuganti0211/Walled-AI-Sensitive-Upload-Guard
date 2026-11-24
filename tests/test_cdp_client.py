"""Unit tests for the CDP client and multi-target connection manager."""

import json
from unittest.mock import MagicMock, patch
import pytest

from app.browser.cdp_client import CDPClient
from app.browser.models import CDPStatus, CandidateRequest


class TestCDPClient:
    """Test suite for CDP target discovery, connection, and request observation."""

    @pytest.fixture
    def client(self, qtbot):
        c = CDPClient(port=9222)
        return c

    def test_initial_state(self, client):
        """Verify default disconnected state."""
        assert client.status == CDPStatus.DISCONNECTED
        assert client.port == 9222
        assert len(client._active_sessions) == 0

    def test_fetch_targets_parses_json(self, client):
        """Verify HTTP /json/list query is correctly parsed."""
        mock_targets = [
            {
                "id": "tab-1",
                "type": "page",
                "title": "ChatGPT",
                "url": "https://chatgpt.com/",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab-1",
            }
        ]
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps(mock_targets).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=mock_response):
            targets = client.fetch_targets()
            assert len(targets) == 1
            assert targets[0]["id"] == "tab-1"
            assert targets[0]["url"] == "https://chatgpt.com/"

    def test_poll_targets_detects_chatgpt_and_perplexity(self, client, qtbot):
        """Verify polling emits site detection signals when target tabs are present."""
        sample_targets = [
            {
                "id": "tab-cg",
                "type": "page",
                "url": "https://chatgpt.com/chat",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab-cg",
            },
            {
                "id": "tab-perp",
                "type": "page",
                "url": "https://www.perplexity.ai/search",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab-perp",
            },
        ]

        with patch.object(client, "fetch_targets", return_value=sample_targets), \
             patch.object(client, "_attach_to_tab"):  # Mock WebSocket connection
            with qtbot.waitSignal(client.chatgpt_detected, timeout=1000) as cg_blocker, \
                 qtbot.waitSignal(client.perplexity_detected, timeout=1000) as perp_blocker:
                client.poll_targets()

            assert cg_blocker.args == [True]
            assert perp_blocker.args == [True]
            assert client.status == CDPStatus.CONNECTED

    def test_duplicate_tab_attachment_prevention(self, client):
        """Verify polling twice does not attach duplicate sessions to the same tab."""
        sample_targets = [
            {
                "id": "tab-1",
                "type": "page",
                "url": "https://chatgpt.com",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab-1",
            }
        ]

        attach_mock = MagicMock()
        with patch.object(client, "fetch_targets", return_value=sample_targets), \
             patch.object(client, "_attach_to_tab", attach_mock):
            # First poll: tab-1 not in _active_sessions -> attaches
            client.poll_targets()
            assert attach_mock.call_count == 1

            # Simulate attached state
            client._active_sessions["tab-1"] = MagicMock()

            # Second poll: tab-1 already in _active_sessions -> must NOT attach again
            client.poll_targets()
            assert attach_mock.call_count == 1  # Count should NOT increase

    def test_process_network_request_emits_prompt_observed(self, client, qtbot):
        """Verify Network.requestWillBeSent emits prompt_observed signal."""
        params = {
            "requestId": "net-req-101",
            "request": {
                "url": "https://chatgpt.com/backend-api/conversation",
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "hasPostData": True,
            },
        }

        with qtbot.waitSignal(client.prompt_observed, timeout=1000) as blocker:
            client._process_network_request(params)

        candidate: CandidateRequest = blocker.args[0]
        assert candidate.platform == "ChatGPT"
        assert candidate.is_candidate_prompt is True
        assert candidate.request_id == "net-req-101"

    def test_process_network_request_duplicate_prevention(self, client, qtbot):
        """Verify the same requestId is not processed twice."""
        params = {
            "requestId": "net-req-101",
            "request": {
                "url": "https://chatgpt.com/backend-api/conversation",
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "hasPostData": True,
            },
        }

        client._observed_request_ids.add("net-req-101")

        # Expect signal NOT to be emitted
        signal_emitted = False

        def on_emit(c):
            nonlocal signal_emitted
            signal_emitted = True

        client.prompt_observed.connect(on_emit)
        client._process_network_request(params)
        assert signal_emitted is False
