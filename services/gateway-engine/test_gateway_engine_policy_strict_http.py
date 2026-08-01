"""C-RT-3 strict HTTP policy enforcement tests."""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))

from api import proxy_routing
from api.policy_hooks import PolicyDeniedError, policy_denial_response


class _Deps:
    def __init__(self, evaluator=None, *, enabled=True, strict=False):
        self.evaluator = evaluator
        self.enabled = enabled
        self.strict = strict
        self.traces = []
        self.model_prefix = "AI-Gateway:"

    def policy_engine_enabled(self):
        return self.enabled

    def policy_engine_strict(self):
        return self.strict

    def team_budget_snapshot_enabled(self):
        return False

    def get_policy_evaluator(self):
        return self.evaluator

    def record_policy_trace(self, decision, elapsed_ms, *, error=None):
        self.traces.append((decision, elapsed_ms, error))

    def load_model_registry(self):
        return SimpleNamespace(models=[])


def _body():
    return {"model": "claude-sonnet-4-6", "metadata": {"caller": "kept"}}


@pytest.mark.asyncio
async def test_strict_deny_raises_without_mutating_request(monkeypatch):
    evaluator = AsyncMock()
    evaluator.evaluate.return_value = {
        "gate": "deny",
        "deny_reason": "secret internal reason",
        "policy_version": "strict-v1",
        "rules_applied": ["repo:block"],
    }
    deps = _Deps(evaluator, strict=True)
    monkeypatch.setattr(proxy_routing, "_deps", lambda: deps)

    body = _body()
    with pytest.raises(PolicyDeniedError) as exc_info:
        await proxy_routing._apply_policy_engine("Bearer ak-tenant-workspace-team-repo-dev", body)

    assert exc_info.value.decision["gate"] == "deny"
    assert body == _body()
    assert deps.traces[0][0]["gate"] == "deny"


@pytest.mark.asyncio
async def test_deny_remains_fail_open_when_strict_flag_is_off(monkeypatch):
    evaluator = AsyncMock()
    evaluator.evaluate.return_value = {"gate": "deny", "policy_version": "v1", "rules_applied": []}
    deps = _Deps(evaluator, strict=False)
    monkeypatch.setattr(proxy_routing, "_deps", lambda: deps)

    body = _body()
    assert await proxy_routing._apply_policy_engine("Bearer ak-tenant-workspace-team-repo-dev", body) is body
    assert "routing_decision" in body["metadata"]


@pytest.mark.asyncio
async def test_malformed_decision_fails_open_and_is_traced(monkeypatch):
    evaluator = AsyncMock()
    evaluator.evaluate.return_value = {"gate": "unexpected", "policy_version": "v1"}
    deps = _Deps(evaluator, strict=True)
    monkeypatch.setattr(proxy_routing, "_deps", lambda: deps)

    body = _body()
    assert await proxy_routing._apply_policy_engine("Bearer ak-tenant-workspace-team-repo-dev", body) is body
    assert "routing_decision" not in body["metadata"]
    assert deps.traces[-1][0] is None
    assert deps.traces[-1][2] == "malformed decision"


@pytest.mark.asyncio
async def test_evaluator_timeout_fails_open_with_bounded_trace(monkeypatch):
    evaluator = AsyncMock()

    async def slow(_context):
        await asyncio.sleep(0.05)

    evaluator.evaluate.side_effect = slow
    deps = _Deps(evaluator, strict=True)
    monkeypatch.setattr(proxy_routing, "_deps", lambda: deps)
    monkeypatch.setattr(proxy_routing, "_policy_engine_timeout_seconds", lambda: 0.001)

    body = _body()
    assert await proxy_routing._apply_policy_engine("Bearer ak-tenant-workspace-team-repo-dev", body) is body
    assert "routing_decision" not in body["metadata"]
    assert deps.traces[-1][2] == "timeout"


@pytest.mark.parametrize("protocol", ["openai", "responses", "claude", "gemini"])
def test_policy_denial_response_is_protocol_typed_and_secret_free(protocol):
    response = policy_denial_response(protocol)
    assert response.status_code == 403
    assert "secret" not in response.body.decode().lower()
    assert b"Request denied by policy." in response.body
    if protocol == "claude":
        assert b"permission_error" in response.body
    elif protocol == "gemini":
        assert b"PERMISSION_DENIED" in response.body
    else:
        assert b"policy_denied" in response.body


def test_strict_flag_is_opt_in_and_supports_gateway_alias(monkeypatch):
    monkeypatch.delenv("POLICY_ENGINE_STRICT", raising=False)
    monkeypatch.delenv("GATEWAY_ENGINE_POLICY_ENGINE_STRICT", raising=False)
    assert proxy_routing._policy_engine_strict_enabled() is False
    monkeypatch.setenv("GATEWAY_ENGINE_POLICY_ENGINE_STRICT", "true")
    assert proxy_routing._policy_engine_strict_enabled() is True


@pytest.mark.parametrize(
    "path,payload,expected_marker",
    (
        ("/v1/chat/completions", {"model": "gpt-5-4", "messages": []}, b"policy_denied"),
        ("/v1/responses", {"model": "gpt-5-4", "input": "hello"}, b"policy_denied"),
        ("/v1/messages", {"model": "claude-sonnet-4-6", "messages": []}, b"permission_error"),
        (
            "/v1beta/models/gemini-3-flash:generateContent",
            {"contents": [{"role": "user", "parts": [{"text": "hello"}]}]},
            b"PERMISSION_DENIED",
        ),
    ),
)
def test_strict_deny_blocks_every_http_protocol_before_upstream(monkeypatch, path, payload, expected_marker):
    import main

    evaluator = AsyncMock()
    evaluator.evaluate.return_value = {
        "gate": "deny",
        "deny_reason": "must not be returned",
        "policy_version": "strict-v1",
        "rules_applied": ["blocked"],
    }
    upstream = AsyncMock()
    upstream.request.return_value = httpx.Response(200, json={"choices": []})
    upstream.build_request.side_effect = lambda *args, **kwargs: httpx.Request(*args, **kwargs)
    monkeypatch.setattr(main, "_policy_evaluator", evaluator)
    monkeypatch.setattr(main, "_client", upstream)
    monkeypatch.setattr(main, "POLICY_ENGINE_ENABLED", True)
    monkeypatch.setattr(main, "POLICY_ENGINE_STRICT", True)

    response = TestClient(main.app).post(path, json=payload)

    assert response.status_code == 403
    assert expected_marker in response.content
    assert b"must not be returned" not in response.content
    upstream.request.assert_not_awaited()
