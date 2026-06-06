"""Policy × failover integration tests (issue 38-17, Gate B)."""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
from conftest import MASTER_KEY

pytestmark = [pytest.mark.mock]

POLICY_ENGINE_URL = os.environ.get("POLICY_ENGINE_URL", "http://localhost:8080")
_TENANT_KEY = "ak-echoares-core-eng-gateway-dev"
_DEFAULT_TENANCY = {
    "tenant_id": "echoares",
    "workspace_id": "core",
    "team_id": "eng",
    "repo_name": "gateway",
    "environment": "dev",
}


@pytest.fixture(scope="session")
def policy_engine():
    with httpx.Client(base_url=POLICY_ENGINE_URL, timeout=10) as client:
        try:
            if client.get("/v1/health").status_code != 200:
                pytest.fail(f"mock policy-engine unhealthy at {POLICY_ENGINE_URL}")
        except httpx.ConnectError as exc:
            pytest.fail(f"mock policy-engine not reachable at {POLICY_ENGINE_URL}: {exc}")
        yield client


@pytest.fixture(autouse=True)
def reset_policy_debug(policy_engine):
    policy_engine.post("/v1/debug/reset")
    yield


def _auth_headers() -> dict[str, str]:
    key = MASTER_KEY or _TENANT_KEY
    return {"Authorization": f"Bearer {key}"}


def _chat(
    client: httpx.Client,
    *,
    model: str,
    metadata: dict | None = None,
    tools: bool = False,
    content: str = "ping",
):
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 5,
    }
    meta = dict(_DEFAULT_TENANCY)
    if metadata:
        meta.update(metadata)
    body["metadata"] = meta
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    return client.post("/v1/chat/completions", json=body, headers=_auth_headers())


def _last_evaluate(policy_engine: httpx.Client) -> dict:
    payload = policy_engine.get("/v1/debug/last").json()
    assert payload, "policy-engine received no /v1/evaluate call"
    return payload


def _last_decision(policy_engine: httpx.Client) -> dict:
    payload = _last_evaluate(policy_engine)
    decision = payload.get("decision")
    assert isinstance(decision, dict), f"unexpected debug payload: {payload}"
    return decision


def _last_context(policy_engine: httpx.Client) -> dict:
    payload = _last_evaluate(policy_engine)
    context = payload.get("context")
    assert isinstance(context, dict), f"unexpected debug payload: {payload}"
    return context


def _policy_trace(client: httpx.Client) -> dict:
    resp = client.get("/admin/status")
    assert resp.status_code == 200, resp.text[:300]
    routing = resp.json().get("panels", {}).get("routing", {})
    trace = routing.get("data", {}).get("policy_engine")
    assert isinstance(trace, dict), f"policy_engine trace missing from admin status: {routing}"
    return trace


@pytest.mark.mock
def test_policy_engine_wired_in_mock_stack(client, policy_engine):
    resp = _chat(client, model="claude-sonnet-4-6")
    assert resp.status_code == 200, resp.text[:300]
    assert _last_decision(policy_engine).get("policy_version") == "mock-gate-b-v1"


@pytest.mark.mock
def test_agent_family_lock_blocks_cross_family_tools(client, policy_engine):
    resp = _chat(
        client,
        model="claude-sonnet-4-6",
        metadata={"agent_id": "test:agent-family-lock"},
        tools=True,
    )
    assert resp.status_code == 200, resp.text[:300]
    decision = _last_decision(policy_engine)
    assert decision.get("lock_model_family") is True
    assert "gemini-2.5-flash" not in decision.get("ordered_deployments", [])
    assert "fallback:affinity:family_lock" in decision.get("rules_applied", [])


@pytest.mark.mock
def test_quota_429_preemptive_deprioritizes_credentials(client, policy_engine):
    resp = _chat(
        client,
        model="claude-sonnet-4-6",
        metadata={"agent_id": "test:quota-429-deprioritize"},
    )
    assert resp.status_code == 200, resp.text[:300]
    decision = _last_decision(policy_engine)
    assert decision.get("quota_aware_mode") is True
    deprioritized = decision.get("deprioritized_credentials") or []
    assert deprioritized == ["cred-hot", "cred-warm"]
    assert "gemini-2.5-flash" not in decision.get("ordered_deployments", [])
    assert decision.get("ordered_deployments") == ["claude-sonnet-4-6", "gpt-5.5"]
    rules = decision.get("rules_applied", [])
    assert "mock:rate_limit:preemptive" in rules
    assert "fallback:rate_limit:cooldown_skip" in rules

    trace = _policy_trace(client)
    last = trace.get("last_decision", {})
    assert last.get("quota_aware_mode") is True
    assert last.get("deprioritized_credentials") == ["cred-hot", "cred-warm"]


@pytest.mark.mock
def test_quota_429_preemptive_from_translator_rate_limit_signals(client, policy_engine):
    seed = _chat(
        client,
        model="claude-sonnet-4-6",
        metadata={"agent_id": "test:seed-429-counter"},
        # LiteLLM drop_params strips metadata before cliproxy; user message reaches mock upstream.
        # Unique suffix avoids LiteLLM response cache collisions across test runs.
        content=f"test:seed-429-counter:{uuid.uuid4().hex}",
    )
    assert seed.status_code == 429, seed.text[:300]

    resp = _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "composer-follow-up"})
    assert resp.status_code == 200, resp.text[:300]

    context = _last_context(policy_engine)
    rate_limits = context.get("rate_limits") or []
    assert any(isinstance(rl, dict) and rl.get("pre_emptive_degraded") for rl in rate_limits), (
        f"expected pre_emptive_degraded rate_limits in context, got {rate_limits}"
    )

    decision = _last_decision(policy_engine)
    assert decision.get("quota_aware_mode") is True
    assert "cred-hot" in (decision.get("deprioritized_credentials") or [])
    assert "gemini-2.5-flash" not in decision.get("ordered_deployments", [])
    assert "mock:rate_limit:preemptive" in decision.get("rules_applied", [])


@pytest.mark.mock
def test_repo_allowlist_restricts_ordered_deployments(client, policy_engine):
    resp = _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:repo-allowlist"})
    assert resp.status_code == 200, resp.text[:300]
    assert _last_decision(policy_engine).get("ordered_deployments") == ["claude-sonnet-4-6"]


@pytest.mark.mock
def test_repo_denylist_gate(client, policy_engine):
    resp = _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:repo-denylist"})
    assert resp.status_code == 200, resp.text[:300]
    decision = _last_decision(policy_engine)
    assert decision.get("gate") == "deny"
    assert decision.get("deny_reason") == "repo denylist"
    assert decision.get("ordered_deployments") == []


@pytest.mark.mock
def test_budget_deny_hard_gate_with_retry_after(client, policy_engine):
    resp = _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:budget-deny"})
    assert resp.status_code == 200, resp.text[:300]
    decision = _last_decision(policy_engine)
    assert decision.get("gate") == "deny"
    assert decision.get("deny_reason") == "budget exhausted"
    assert decision.get("retry_after_seconds") == 60
    assert "mock:budget:hard_deny" in decision.get("rules_applied", [])
    assert decision.get("quota_aware_mode") is False

    trace = _policy_trace(client)
    last = trace.get("last_decision", {})
    assert last.get("gate") == "deny"
    assert "deprioritized_credentials" not in last


@pytest.mark.mock
def test_cooldown_skip_removes_degraded_fallback(client, policy_engine):
    resp = _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:cooldown-skip"})
    assert resp.status_code == 200, resp.text[:300]
    decision = _last_decision(policy_engine)
    ordered = decision.get("ordered_deployments", [])
    fallback = decision.get("fallback_chain", [])
    assert ordered[0] == "claude-sonnet-4-6"
    assert "gemini-2.5-flash" not in ordered
    assert "gpt-5.5" in ordered
    assert fallback == ["gpt-5.5"]
    rules = decision.get("rules_applied", [])
    assert "mock:cooldown_skip" in rules
    assert "fallback:rate_limit:cooldown_skip" in rules


@pytest.mark.mock
def test_inventory_exclude_deprioritizes_degraded_credentials(client, policy_engine):
    resp = _chat(
        client,
        model="claude-sonnet-4-6",
        metadata={"agent_id": "test:inventory-exclude"},
    )
    assert resp.status_code == 200, resp.text[:300]
    decision = _last_decision(policy_engine)
    assert decision.get("quota_aware_mode") is True
    assert decision.get("deprioritized_credentials") == ["cred-degraded"]
    ordered = decision.get("ordered_deployments", [])
    assert ordered[0] == "claude-sonnet-4-6"
    assert "gemini-2.5-flash" not in ordered
    assert "gpt-5.5" in ordered
    rules = decision.get("rules_applied", [])
    assert "mock:inventory:exclude" in rules
    assert "rate_limit:inventory_cooldown_merged" in rules
    assert "fallback:rate_limit:cooldown_skip" in rules

    trace = _policy_trace(client)
    last = trace.get("last_decision", {})
    assert last.get("deprioritized_credentials") == ["cred-degraded"]


@pytest.mark.mock
def test_admin_status_reports_policy_engine_enabled(client):
    resp = client.get("/admin/status")
    assert resp.status_code == 200
    routing = resp.json().get("panels", {}).get("routing", {})
    assert routing.get("data", {}).get("policy_engine_enabled") is True
