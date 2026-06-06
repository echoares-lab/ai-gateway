"""Unit tests for Codex WebSocket policy bypass and in-process evaluate (#182)."""

import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))
import main as t


class TestCodexWsPolicyBypass(unittest.TestCase):
    def tearDown(self):
        for key in ("POLICY_ENGINE_ENABLED", "POLICY_ENGINE_WS_EVALUATE"):
            os.environ.pop(key, None)

    def test_default_bypasses_policy_engine(self):
        assert t.codex_ws_policy_bypass() is True

    def test_ws_evaluate_alone_still_bypasses(self):
        os.environ["POLICY_ENGINE_WS_EVALUATE"] = "true"
        assert t.codex_ws_policy_bypass() is True

    def test_policy_enabled_alone_still_bypasses(self):
        os.environ["POLICY_ENGINE_ENABLED"] = "true"
        assert t.codex_ws_policy_bypass() is True

    def test_both_flags_disable_bypass(self):
        os.environ["POLICY_ENGINE_ENABLED"] = "true"
        os.environ["POLICY_ENGINE_WS_EVALUATE"] = "true"
        assert t.codex_ws_policy_bypass() is False


class TestCodexWsUpstreamHeaders(unittest.TestCase):
    def test_strips_handshake_headers_and_sets_cliproxy_auth(self):
        with patch.dict(os.environ, {"CLIPROXY_API_KEY": "cliproxy-test-key"}, clear=False):
            headers = t._codex_ws_upstream_headers(
                {
                    "host": "localhost:4000",
                    "upgrade": "websocket",
                    "connection": "Upgrade",
                    "sec-websocket-key": "abc",
                    "authorization": "Bearer sk-client",
                    "x-custom": "keep-me",
                }
            )
        assert "host" not in {k.lower() for k in headers}
        assert "sec-websocket-key" not in {k.lower() for k in headers}
        assert headers["authorization"] == "Bearer cliproxy-test-key"
        assert headers["x-custom"] == "keep-me"

    def test_injects_routing_decision_metadata(self):
        with patch.dict(os.environ, {"CLIPROXY_API_KEY": "cliproxy-test-key"}, clear=False):
            headers = t._codex_ws_upstream_headers(
                {"authorization": "Bearer sk-client"},
                routing_decision={
                    "session_key": "sess-abc",
                    "quota_aware_mode": True,
                    "deprioritized_credentials": ["cred-1", "cred-2"],
                },
            )
        assert headers["x-session-id"] == "sess-abc"
        assert headers["x-quota-aware-mode"] == "true"
        assert headers["x-deprioritized-credentials"] == "cred-1,cred-2"


class TestAdminRoutingPanelWsBypass(unittest.TestCase):
    def tearDown(self):
        for key in ("POLICY_ENGINE_ENABLED", "POLICY_ENGINE_WS_EVALUATE"):
            os.environ.pop(key, None)

    def test_routing_panel_reports_websocket_bypass(self):
        panel = t._admin_routing_panel({}, "", [])
        data = panel["data"]
        assert data["websocket_policy_bypass"] is True
        assert data["websocket_policy_evaluate_enabled"] is False
        assert data["policy_engine_enabled"] is False


class TestCodexWsPolicyEvaluate(unittest.IsolatedAsyncioTestCase):
    async def test_ws_evaluate_applies_routing_decision_to_upstream_headers(self):
        os.environ["POLICY_ENGINE_ENABLED"] = "true"
        os.environ["POLICY_ENGINE_WS_EVALUATE"] = "true"

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate = AsyncMock(
            return_value={
                "gate": "allow",
                "session_key": "ws-sess-1",
                "quota_aware_mode": True,
                "deprioritized_credentials": ["cred-ws"],
            }
        )

        with patch.object(t, "_policy_evaluator", mock_evaluator):
            ctx = t._build_ws_routing_context(
                type("WS", (), {"query_params": {"model": "gpt-5-4"}, "headers": {}})(),
                "ak-echoares-core-eng-gateway-dev",
            )
            decision = await t._evaluate_policy_engine(ctx)

        assert decision is not None
        assert decision["session_key"] == "ws-sess-1"
        headers = t._codex_ws_upstream_headers({}, routing_decision=decision)
        assert headers["x-session-id"] == "ws-sess-1"
        assert headers["x-quota-aware-mode"] == "true"
        assert headers["x-deprioritized-credentials"] == "cred-ws"
        mock_evaluator.evaluate.assert_awaited_once()

    def tearDown(self):
        for key in ("POLICY_ENGINE_ENABLED", "POLICY_ENGINE_WS_EVALUATE"):
            os.environ.pop(key, None)


if __name__ == "__main__":
    unittest.main()
