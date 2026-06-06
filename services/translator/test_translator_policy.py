"""Unit tests for translator in-process policy integration (issue 182)."""

import os
import sys
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import main as t


@pytest.fixture
def policy_client(monkeypatch, policy_engine_env):
    state = {"policy_calls": 0}

    mock_evaluator = AsyncMock()

    async def mock_evaluate(context):
        state["policy_calls"] += 1
        return {
            "gate": "allow",
            "allowed_models": ["claude-sonnet-4-6"],
            "policy_version": "v0-stub",
            "rules_applied": ["stub:pass_through"],
        }

    mock_evaluator.evaluate.side_effect = mock_evaluate
    monkeypatch.setattr(t, "_policy_evaluator", mock_evaluator)

    # Mock LiteLLM
    async def mock_litellm(*args, **kwargs):
        return httpx.Response(
            200, content=b'{"id": "resp_123", "choices": []}', request=httpx.Request("POST", "http://litellm")
        )

    with patch.object(t, "_client", AsyncMock()):
        with patch.object(t._client, "request", side_effect=mock_litellm):
            yield TestClient(t.app), state


def test_policy_enabled_injects_routing_decision(policy_client):
    client, state = policy_client
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    assert state["policy_calls"] == 1


def test_policy_fail_open_on_error(policy_client, monkeypatch):
    client, state = policy_client

    async def mock_error(context):
        state["policy_calls"] += 1
        raise Exception("broken")

    t._policy_evaluator.evaluate.side_effect = mock_error

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    assert state["policy_calls"] == 1


def test_policy_disabled_skips_evaluate(policy_client, monkeypatch):
    client, state = policy_client
    monkeypatch.setattr(t, "POLICY_ENGINE_ENABLED", False)

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    assert state["policy_calls"] == 0
