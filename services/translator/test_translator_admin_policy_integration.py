"""Gate A integration tests: policy-engine mock → chat evaluate → /admin/status trace.

Exercises the wired path beyond unit helpers in test_translator_admin_policy_trace.py:
mocked policy-engine HTTP responses drive _evaluate_policy_engine, _record_policy_trace,
and the live /admin/status routing.policy_engine panel.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import main as t


def _reset_policy_trace() -> None:
    t._policy_trace.evaluate_ms = None
    t._policy_trace.evaluated_at = None
    t._policy_trace.decision = None
    t._policy_trace.error = None
    t._policy_version_hint = None


class _MockResponse:
    def __init__(self, status_code: int = 200, content: bytes | None = None):
        self.status_code = status_code
        self.content = content if content is not None else b'{"id": "resp_mock", "choices": [{"message": {"content": "ok"}}]}'
        self.headers = {"content-type": "application/json"}
        self.text = self.content.decode()

    def json(self):
        return json.loads(self.content.decode())


@contextmanager
def _admin_status_patches():
    async def fake_visible():
        return ["claude-sonnet-4-6"], []

    async def fake_metrics():
        return "", []

    with (
        patch.object(t, "_admin_load_litellm_config", return_value=({"model_list": []}, [])),
        patch.object(t, "_admin_fetch_visible_models", fake_visible),
        patch.object(t, "_admin_fetch_metrics_text", fake_metrics),
        patch.object(t, "_admin_run_readonly_command", lambda *a, **k: ("", [])),
    ):
        yield


def _routing_policy_engine(client: TestClient) -> dict:
    resp = client.get("/admin/status")
    assert resp.status_code == 200
    routing = resp.json()["panels"]["routing"]["data"]
    assert "policy_engine" in routing, routing
    return routing["policy_engine"]


@pytest.fixture
def policy_admin_client(monkeypatch):
    """Mock policy-engine + LiteLLM HTTP; policy trace enabled."""
    _reset_policy_trace()
    monkeypatch.setattr(t, "POLICY_ENGINE_ENABLED", True)
    monkeypatch.setenv("POLICY_ENGINE_ENABLED", "true")
    monkeypatch.setattr(t, "ADMIN_POLICY_TRACE_ENABLED", True)
    monkeypatch.setattr(t, "POLICY_ENGINE_URL", "http://policy-engine:8080")
    monkeypatch.setattr(t, "POLICY_ENGINE_TIMEOUT_MS", 100)

    state: dict = {
        "evaluate_calls": 0,
        "health_calls": 0,
        "evaluate_decision": {
            "gate": "allow",
            "policy_version": "mock-integration-v1",
            "quota_aware_mode": True,
            "deprioritized_credentials": ["cred-hot", "cred-warm"],
            "session_key": "sess-integration-secret",
            "rules_applied": ["quota:deprioritize", "repo:affinity"],
        },
        "health_body": {"policy_version": "mock-health-v2"},
        "evaluate_error": None,
        "evaluate_status": 200,
    }

    async def mock_request(method, url, **kwargs):
        url_s = str(url)
        if "policy-engine" in url_s and url_s.endswith("/v1/evaluate"):
            state["evaluate_calls"] += 1
            if state["evaluate_error"] == "timeout":
                raise httpx.TimeoutException("timed out")
            if state["evaluate_error"] == "connect":
                raise httpx.ConnectError("connection refused")
            if state["evaluate_status"] != 200:
                return _MockResponse(
                    status_code=state["evaluate_status"],
                    content=b'{"error": "policy unavailable"}',
                )
            return _MockResponse(
                content=json.dumps({"decision": state["evaluate_decision"]}).encode(),
            )
        if "policy-engine" in url_s and url_s.endswith("/v1/health"):
            state["health_calls"] += 1
            return _MockResponse(content=json.dumps(state["health_body"]).encode())
        if "litellm" in url_s:
            return _MockResponse()
        raise AssertionError(f"unexpected HTTP call: {method} {url_s}")

    t._client = httpx.AsyncClient()
    t._client.request = mock_request
    client = TestClient(t.app)
    yield client, state
    t._client = None
    _reset_policy_trace()


def test_chat_evaluate_populates_admin_policy_trace(policy_admin_client):
    """Chat completion triggers mocked evaluate; /admin/status exposes redacted trace."""
    client, state = policy_admin_client
    with _admin_status_patches():
        chat = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer ak-echoares-core-eng-gateway-dev"},
            json={
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "ping"}],
            },
        )
        assert chat.status_code == 200
        assert state["evaluate_calls"] == 1

        trace = _routing_policy_engine(client)

    assert trace["enabled"] is True
    assert trace["trace_enabled"] is True
    assert trace["last_evaluate_ms"] is not None
    assert trace["last_evaluate_ms"] >= 0
    assert trace["policy_version"] == "mock-health-v2"
    assert state["health_calls"] >= 1

    decision = trace["last_decision"]
    assert decision["gate"] == "allow"
    assert decision["quota_aware_mode"] is True
    assert decision["deprioritized_credentials"] == ["cred-hot", "cred-warm"]
    assert decision["rules_applied"] == ["quota:deprioritize", "repo:affinity"]
    assert decision["session_key"] == "[redacted]"
    assert "sess-integration-secret" not in json.dumps(trace)


def test_admin_status_uses_decision_policy_version_when_health_missing(policy_admin_client):
    """When /v1/health has no version, trace falls back to last decision policy_version."""
    client, state = policy_admin_client
    state["health_body"] = {}
    state["evaluate_decision"]["policy_version"] = "mock-from-decision"

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        trace = _routing_policy_engine(client)

    assert trace["policy_version"] == "mock-from-decision"


def test_admin_status_surfaces_evaluate_timeout(policy_admin_client):
    client, state = policy_admin_client
    state["evaluate_error"] = "timeout"

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        trace = _routing_policy_engine(client)

    assert trace["last_error"] == "timeout"
    assert "last_decision" not in trace


def test_admin_status_surfaces_evaluate_http_error(policy_admin_client):
    client, state = policy_admin_client
    state["evaluate_status"] = 503

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        trace = _routing_policy_engine(client)

    assert trace["last_error"] == "http 503"
    assert "last_decision" not in trace


def test_admin_trace_disabled_omits_policy_engine_panel(policy_admin_client, monkeypatch):
    monkeypatch.setattr(t, "ADMIN_POLICY_TRACE_ENABLED", False)
    monkeypatch.setenv("ADMIN_POLICY_TRACE_ENABLED", "false")
    client, state = policy_admin_client

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        resp = client.get("/admin/status")

    routing = resp.json()["panels"]["routing"]["data"]
    assert "policy_engine" not in routing
    assert routing["policy_engine_enabled"] is True


def test_admin_quota_fields_hidden_when_not_quota_aware(policy_admin_client):
    client, state = policy_admin_client
    state["evaluate_decision"] = {
        "gate": "allow",
        "policy_version": "mock-integration-v1",
        "quota_aware_mode": False,
        "deprioritized_credentials": ["cred-hidden"],
        "session_key": "sess-x",
        "rules_applied": ["stub"],
    }

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        trace = _routing_policy_engine(client)

    decision = trace["last_decision"]
    assert decision["quota_aware_mode"] is False
    assert "deprioritized_credentials" not in decision
