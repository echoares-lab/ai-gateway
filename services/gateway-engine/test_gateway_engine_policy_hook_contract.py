"""C-AUD-8 contract tests for the policy-hook extraction boundary.

These tests deliberately exercise the existing seam without extracting it.
The implementation child must keep these invariants while moving the hooks
behind an injectable interface.
"""

import asyncio
import inspect
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import main as gateway_main
from api import proxy_catchall, proxy_claude, proxy_gemini, proxy_responses, proxy_routing

HTTP_CALL_SITES = {
    proxy_catchall: "proxy",
    proxy_responses: "responses_proxy",
    proxy_claude: "claude_proxy",
    proxy_gemini: "gemini_proxy",
}


def test_http_call_sites_use_shared_policy_apply_hook():
    """All HTTP adapters must retain one shared policy application seam."""
    for module, function_name in HTTP_CALL_SITES.items():
        source = inspect.getsource(getattr(module, function_name))
        assert "_policy_hooks" in source, (module.__name__, function_name)
        assert "_extract_and_apply_tenancy" in source, (module.__name__, function_name)


class _PolicyDeps:
    def __init__(self, evaluator=None, enabled=True):
        self.evaluator = evaluator
        self.enabled = enabled
        self.traces = []
        self.model_prefix = "AI-Gateway:"

    def policy_engine_enabled(self):
        return self.enabled

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
async def test_disabled_policy_skips_evaluation_and_preserves_body(monkeypatch):
    evaluator = AsyncMock()
    deps = _PolicyDeps(evaluator, enabled=False)
    monkeypatch.setattr(proxy_routing, "_deps", lambda: deps)

    body = _body()
    result = await proxy_routing._apply_policy_engine("Bearer ak-tenant-workspace-team-repo-dev", body)

    assert result is body
    assert result == _body()
    evaluator.evaluate.assert_not_awaited()
    assert deps.traces == []


@pytest.mark.asyncio
async def test_enabled_policy_applies_only_routing_decision_metadata(monkeypatch):
    evaluator = AsyncMock()
    evaluator.evaluate.return_value = {
        "gate": "allow",
        "policy_version": "contract-v1",
        "rules_applied": ["allowlisted"],
        "session_key": "internal-session",
    }
    deps = _PolicyDeps(evaluator)
    monkeypatch.setattr(proxy_routing, "_deps", lambda: deps)

    result = await proxy_routing._apply_policy_engine("Bearer ak-tenant-workspace-team-repo-dev", _body())

    assert result["metadata"]["caller"] == "kept"
    assert result["metadata"]["routing_decision"]["policy_version"] == "contract-v1"
    evaluator.evaluate.assert_awaited_once()
    assert deps.traces[0][0]["gate"] == "allow"
    assert deps.traces[0][2] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("broken"), asyncio.TimeoutError()])
async def test_evaluator_failures_are_fail_open_and_traced(monkeypatch, failure):
    evaluator = AsyncMock()
    evaluator.evaluate.side_effect = failure
    deps = _PolicyDeps(evaluator)
    monkeypatch.setattr(proxy_routing, "_deps", lambda: deps)

    body = _body()
    result = await proxy_routing._apply_policy_engine("Bearer ak-tenant-workspace-team-repo-dev", body)

    assert result is body
    assert "routing_decision" not in result["metadata"]
    assert len(deps.traces) == 1
    assert deps.traces[0][0] is None
    assert deps.traces[0][2] is not None


@pytest.mark.asyncio
async def test_missing_evaluator_is_fail_open_and_traced(monkeypatch):
    deps = _PolicyDeps(None)
    monkeypatch.setattr(proxy_routing, "_deps", lambda: deps)

    body = _body()
    result = await proxy_routing._apply_policy_engine("Bearer ak-tenant-workspace-team-repo-dev", body)

    assert result is body
    assert "routing_decision" not in result["metadata"]
    assert deps.traces == [(None, deps.traces[0][1], "evaluator unavailable")]


def test_admin_redaction_exposes_only_bounded_safe_fields():
    decision = {
        "gate": "allow",
        "rules_applied": ["safe-rule"],
        "policy_version": "v1",
        "quota_aware_mode": True,
        "deprioritized_credentials": ["cred-a"],
        "session_key": "secret-session",
        "tenancy": {"tenant_id": "secret-tenant"},
        "prompt": "secret prompt",
        "api_key": "sk-secret",
    }

    redacted = gateway_main._redact_policy_decision_for_admin(decision)

    assert redacted == {
        "gate": "allow",
        "rules_applied": ["safe-rule"],
        "policy_version": "v1",
        "quota_aware_mode": True,
        "deprioritized_credentials": ["cred-a"],
        "session_key": "[redacted]",
    }
    assert "api_key" not in redacted
    assert "tenancy" not in redacted


def test_websocket_policy_is_default_bypass_and_explicit_opt_in():
    keys = ("POLICY_ENGINE_ENABLED", "POLICY_ENGINE_WS_EVALUATE")
    try:
        for enabled, ws_enabled, expected in (
            (False, False, True),
            (True, False, True),
            (False, True, True),
            (True, True, False),
        ):
            os.environ["POLICY_ENGINE_ENABLED"] = str(enabled).lower()
            os.environ["POLICY_ENGINE_WS_EVALUATE"] = str(ws_enabled).lower()
            assert gateway_main.codex_ws_policy_bypass() is expected
    finally:
        for key in keys:
            os.environ.pop(key, None)
