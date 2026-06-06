"""Gate A integration tests: in-process policy evaluate → chat → /admin/status trace."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

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
    """Mock in-process evaluator + LiteLLM HTTP; policy trace enabled."""
    _reset_policy_trace()
    monkeypatch.setattr(t, "POLICY_ENGINE_ENABLED", True)
    monkeypatch.setenv("POLICY_ENGINE_ENABLED", "true")
    monkeypatch.setattr(t, "ADMIN_POLICY_TRACE_ENABLED", True)

    state: dict = {
        "evaluate_calls": 0,
        "evaluate_decision": {
            "gate": "allow",
            "policy_version": "mock-integration-v1",
            "quota_aware_mode": True,
            "deprioritized_credentials": ["cred-hot", "cred-warm"],
            "session_key": "sess-integration-secret",
            "rules_applied": ["quota:deprioritize", "repo:affinity"],
        },
        "evaluate_error": None,
    }

    async def mock_evaluate(context):
        state["evaluate_calls"] += 1
        if state["evaluate_error"] == "failed":
            return None
        return dict(state["evaluate_decision"])

    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(side_effect=mock_evaluate)
    monkeypatch.setattr(t, "_policy_evaluator", mock_evaluator)

    async def mock_request(method, url, **kwargs):
        if "litellm" in str(url):
            return _MockResponse()
        raise AssertionError(f"unexpected HTTP call: {method} {url}")

    t._client = httpx.AsyncClient()
    t._client.request = mock_request
    client = TestClient(t.app)
    yield client, state
    t._client = None
    monkeypatch.setattr(t, "_policy_evaluator", None)
    _reset_policy_trace()


def test_chat_evaluate_populates_admin_policy_trace(policy_admin_client):
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
    assert trace["policy_version"] == "mock-integration-v1"

    decision = trace["last_decision"]
    assert decision["gate"] == "allow"
    assert decision["quota_aware_mode"] is True
    assert decision["deprioritized_credentials"] == ["cred-hot", "cred-warm"]
    assert decision["rules_applied"] == ["quota:deprioritize", "repo:affinity"]
    assert decision["session_key"] == "[redacted]"
    assert "sess-integration-secret" not in json.dumps(trace)


def test_admin_status_uses_decision_policy_version(policy_admin_client):
    client, state = policy_admin_client
    state["evaluate_decision"]["policy_version"] = "mock-from-decision"

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        trace = _routing_policy_engine(client)

    assert trace["policy_version"] == "mock-from-decision"


def test_admin_status_surfaces_evaluate_failure(policy_admin_client):
    client, state = policy_admin_client
    state["evaluate_error"] = "failed"

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        trace = _routing_policy_engine(client)

    assert trace["last_error"] == "evaluate failed"
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
