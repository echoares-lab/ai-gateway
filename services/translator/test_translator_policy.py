"""Unit tests for translator in-process policy integration (issues 38-4, #182)."""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import main as t


@pytest.fixture
def policy_client(monkeypatch):
    monkeypatch.setattr(t, "POLICY_ENGINE_ENABLED", True)
    monkeypatch.setattr(t, "_quota_headroom_cache", None)

    class MockResponse:
        def __init__(self, status_code=200, content=None):
            self.status_code = status_code
            self.content = content if content is not None else b'{"id": "resp_123", "choices": []}'
            self.headers = {"content-type": "application/json"}
            self.text = self.content.decode()

        def json(self):
            return json.loads(self.content.decode())

    state = {"policy_calls": 0, "litellm_body": None}

    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(
        side_effect=lambda context: (
            state.__setitem__("policy_calls", state["policy_calls"] + 1),
            {
                "gate": "allow",
                "allowed_models": ["claude-sonnet-4-6"],
                "policy_version": "v0-stub",
                "rules_applied": ["stub:pass_through"],
            },
        )[1]
    )

    async def mock_request(method, url, **kwargs):
        state["litellm_body"] = kwargs.get("content") or kwargs.get("data")
        return MockResponse()

    t._client = httpx.AsyncClient()
    t._client.request = mock_request
    monkeypatch.setattr(t, "_policy_evaluator", mock_evaluator)
    yield TestClient(t.app), state
    t._client = None
    monkeypatch.setattr(t, "_policy_evaluator", None)
    monkeypatch.setattr(t, "_quota_headroom_cache", None)


def test_policy_disabled_skips_evaluate(monkeypatch):
    monkeypatch.setattr(t, "POLICY_ENGINE_ENABLED", False)
    state = {"policy_calls": 0}

    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(
        side_effect=lambda context: (
            state.__setitem__("policy_calls", state["policy_calls"] + 1),
            {"gate": "allow"},
        )[1]
    )
    monkeypatch.setattr(t, "_policy_evaluator", mock_evaluator)

    class MockResponse:
        status_code = 200
        content = b'{"id": "resp_123", "choices": []}'
        headers = {"content-type": "application/json"}

        def json(self):
            return json.loads(self.content.decode())

    async def mock_request(method, url, **kwargs):
        return MockResponse()

    t._client = httpx.AsyncClient()
    t._client.request = mock_request
    client = TestClient(t.app)
    try:
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer ak-echoares-core-eng-gateway-dev"},
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200
        assert state["policy_calls"] == 0
    finally:
        t._client = None


def test_policy_enabled_injects_routing_decision(policy_client):
    client, state = policy_client
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer ak-echoares-core-eng-gateway-dev"},
        json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert state["policy_calls"] == 1
    body_data = json.loads(state["litellm_body"].decode())
    assert body_data["metadata"]["routing_decision"]["gate"] == "allow"


def test_policy_evaluate_failure_omits_routing_decision(policy_client):
    client, state = policy_client

    async def fail_evaluate(context):
        state["policy_calls"] += 1
        return None

    t._policy_evaluator.evaluate = fail_evaluate
    response = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-5-4", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert "routing_decision" not in json.loads(state["litellm_body"].decode()).get("metadata", {})


def test_build_routing_context_includes_tenancy_and_capabilities():
    ctx = t._build_routing_context(
        "ak-echoares-core-eng-gateway-dev",
        {
            "model": "claude-sonnet-4-6",
            "tools": [{}],
            "messages": [{"role": "user", "content": [{"type": "input_image", "url": "http://x"}]}],
            "metadata": {"agent_id": "composer-1"},
        },
    )
    assert ctx["tenancy"]["repo_name"] == "gateway"
    assert ctx["capabilities"]["has_tools"] is True
    assert ctx["agent_id"] == "composer-1"


def test_routing_context_includes_quota_headroom(monkeypatch):
    monkeypatch.setattr(
        t,
        "_quota_headroom_cache",
        [{"credential_id": "cred-a", "provider": "anthropic", "headroom_pct": 12.5, "below_soft_threshold": True}],
    )
    ctx = t._build_routing_context(None, {"model": "claude-sonnet-4-6", "messages": []})
    assert ctx["quota_headroom"][0]["credential_id"] == "cred-a"


def test_parse_team_info_to_budget_pct():
    snapshot = t._parse_team_info_to_budget({"max_budget": 100.0, "spend": 85.0})
    assert snapshot["team_budget_pct_used"] == 85.0


def test_build_routing_context_includes_budget():
    ctx = t._build_routing_context(None, {"model": "x", "messages": []}, budget={"team_budget_pct_used": 100.0})
    assert ctx["budget"]["team_budget_pct_used"] == 100.0


@pytest.mark.asyncio
async def test_load_team_budget_snapshot_from_override(monkeypatch):
    monkeypatch.setattr(t, "TEAM_BUDGET_SNAPSHOT_ENABLED", True)
    monkeypatch.setenv("TEAM_BUDGET_SNAPSHOT_JSON", '{"team_budget_pct_used": 99.0}')
    snapshot = await t._load_team_budget_snapshot({"tenant_id": "echoares", "workspace_id": "core", "team_id": "eng"})
    assert snapshot["team_budget_pct_used"] == 99.0


def test_rate_limit_hints_from_provider_counter():
    t.PROVIDER_RATE_LIMITS.labels(provider="anthropic", model="claude-sonnet-4-6").inc()
    hints = t._build_rate_limit_hints("claude-sonnet-4-6")
    assert hints and hints[0]["pre_emptive_degraded"] is True


@pytest.mark.asyncio
async def test_evaluate_policy_engine_returns_none_when_evaluator_missing(monkeypatch):
    monkeypatch.setattr(t, "_policy_evaluator", None)
    assert await t._evaluate_policy_engine({"requested_model": "gpt-5-4"}) is None
