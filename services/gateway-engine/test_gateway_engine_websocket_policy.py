"""Unit tests for Codex WebSocket policy bypass (issue 38-14)."""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))
import main as t


class TestCodexWsAuth(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("LITELLM_MASTER_KEY", None)

    def test_validate_ws_auth_missing_credentials(self):
        assert t._validate_ws_auth_token("") == (False, None)

    def test_validate_ws_auth_master_key(self):
        os.environ["LITELLM_MASTER_KEY"] = "master-secret"
        ok, token = t._validate_ws_auth_token("Bearer master-secret")
        assert ok is True
        assert token == "master-secret"

    def test_validate_ws_auth_sk_prefix(self):
        ok, token = t._validate_ws_auth_token("Bearer sk-test-key-123")
        assert ok is True
        assert token == "sk-test-key-123"

    def test_validate_ws_auth_invalid_token(self):
        os.environ["LITELLM_MASTER_KEY"] = "master-secret"
        ok, token = t._validate_ws_auth_token("Bearer wrong")
        assert ok is False
        assert token == "wrong"

    def test_ws_log_safe_mapping_redacts_auth(self):
        safe = t._ws_log_safe_mapping({"authorization": "Bearer sk-secret", "user-agent": "test", "key": "sk-q"})
        assert safe["authorization"] == "[redacted]"
        assert safe["key"] == "[redacted]"
        assert safe["user-agent"] == "test"

    @patch("api.ws_router.httpx.AsyncClient")
    def test_validate_ws_auth_async_rejects_unknown_sk(self, mock_client_cls):
        mock_client = mock_client_cls.return_value.__aenter__.return_value
        mock_client.get = AsyncMock(return_value=type("R", (), {"status_code": 401})())
        ok, token = asyncio.run(t._validate_ws_auth_token_async("Bearer sk-unknown-key-99"))
        assert ok is False
        assert token == "sk-unknown-key-99"

    @patch("api.ws_router.httpx.AsyncClient")
    def test_validate_ws_auth_async_accepts_litellm_key(self, mock_client_cls):
        mock_client = mock_client_cls.return_value.__aenter__.return_value
        mock_client.get = AsyncMock(return_value=type("R", (), {"status_code": 200})())
        ok, token = asyncio.run(t._validate_ws_auth_token_async("Bearer sk-valid-key-12345"))
        assert ok is True
        assert token == "sk-valid-key-12345"


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


if __name__ == "__main__":
    unittest.main()
