"""Gate A integration tests: in-process policy evaluator -> chat evaluate -> /admin/status trace."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

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
    """Mock in-process policy-evaluator; policy trace enabled."""
    _reset_policy_trace()
    monkeypatch.setattr(t, "POLICY_ENGINE_ENABLED", True)
    monkeypatch.setattr(t, "ADMIN_POLICY_TRACE_ENABLED", True)

    state = {
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

    mock_evaluator = AsyncMock()

    async def mock_evaluate(context):
        state["evaluate_calls"] += 1
        if state["evaluate_error"]:
            raise Exception(state["evaluate_error"])
        return state["evaluate_decision"]

    mock_evaluator.evaluate.side_effect = mock_evaluate
    monkeypatch.setattr(t, "_policy_evaluator", mock_evaluator)

    # Mock LiteLLM using httpx.Response
    async def mock_litellm(*args, **kwargs):
        return httpx.Response(
            200,
            content=b'{"id": "resp_mock", "choices": [{"message": {"content": "ok"}}]}',
            request=httpx.Request("POST", "http://litellm"),
        )

    with patch.object(t, "_client", AsyncMock()):
        with patch.object(t._client, "request", side_effect=mock_litellm):
            yield TestClient(t.app), state


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
        assert trace["last_decision"]["gate"] == "allow"
        assert trace["last_decision"]["policy_version"] == "mock-integration-v1"


def test_admin_status_surfaces_evaluate_error(policy_admin_client):
    client, state = policy_admin_client
    state["evaluate_error"] = "broken"

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        trace = _routing_policy_engine(client)
        assert trace["last_error"] == "broken"


def test_admin_status_uses_decision_policy_version_when_health_missing(policy_admin_client):
    client, state = policy_admin_client
    state["evaluate_decision"]["policy_version"] = "mock-from-decision"

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        trace = _routing_policy_engine(client)
        assert trace["policy_version"] == "mock-from-decision"


def test_admin_quota_fields_hidden_when_not_quota_aware(policy_admin_client):
    client, state = policy_admin_client
    state["evaluate_decision"]["quota_aware_mode"] = False

    with _admin_status_patches():
        client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        trace = _routing_policy_engine(client)
        decision = trace["last_decision"]
        assert "quota_aware_mode" not in decision
        assert "deprioritized_credentials" not in decision
