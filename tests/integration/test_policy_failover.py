"""Policy × failover integration tests (issue 38-17, Gate B)."""

from __future__ import annotations

import os
import re
import uuid
import json

import httpx
import pytest
import pytest_asyncio
import respx

from conftest import MASTER_KEY

pytestmark = [pytest.mark.mock, pytest.mark.asyncio]

_TENANT_KEY = "ak-echoares-core-eng-gateway-dev"
_DEFAULT_TENANCY = {
    "tenant_id": "echoares",
    "workspace_id": "core",
    "team_id": "eng",
    "repo_name": "gateway",
    "environment": "dev",
}


@pytest.fixture
async def client(asgi_client):
    """Alias for asgi_client to minimize test changes."""
    return asgi_client


@pytest.fixture
async def policy_debug(asgi_client):
    """In-process mock scenario debug endpoints on the translator."""
    return asgi_client


@pytest_asyncio.fixture(autouse=True)
async def reset_policy_debug(policy_debug):
    await policy_debug.post("/debug/policy/reset")
    yield


def _auth_headers() -> dict[str, str]:
    key = MASTER_KEY or _TENANT_KEY
    return {"Authorization": f"Bearer {key}"}


async def _chat(
    client: httpx.AsyncClient,
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
    return await client.post("/v1/chat/completions", json=body, headers=_auth_headers())


async def _last_evaluate(policy_debug: httpx.AsyncClient) -> dict:
    resp = await policy_debug.get("/debug/policy/last")
    assert resp.status_code == 200, f"debug/policy/last failed: {resp.text}"
    payload = resp.json()
    assert payload, "translator received no in-process policy evaluate call"
    return payload


async def _last_decision(policy_debug: httpx.AsyncClient) -> dict:
    payload = await _last_evaluate(policy_debug)
    decision = payload.get("decision")
    assert isinstance(decision, dict), f"unexpected debug payload: {payload}"
    return decision


async def _last_context(policy_debug: httpx.AsyncClient) -> dict:
    payload = await _last_evaluate(policy_debug)
    context = payload.get("context")
    assert isinstance(context, dict), f"unexpected debug payload: {payload}"
    return context


async def _policy_trace(client: httpx.AsyncClient) -> dict:
    resp = await client.get("/admin/status")
    assert resp.status_code == 200, resp.text[:300]
    routing = resp.json().get("panels", {}).get("routing", {})
    trace = routing.get("data", {}).get("policy_engine")
    assert isinstance(trace, dict), f"policy_engine trace missing from admin status: {routing}"
    return trace


@pytest.mark.mock
async def test_policy_engine_wired_in_mock_stack(client, policy_debug, mock_litellm_router):
    resp = await _chat(client, model="claude-sonnet-4-6")
    assert resp.status_code == 200, resp.text[:300]
    assert (await _last_decision(policy_debug)).get("policy_version") == "mock-gate-b-v1"


@pytest.mark.mock
async def test_agent_family_lock_blocks_cross_family_tools(client, policy_debug, mock_litellm_router):
    resp = await _chat(
        client,
        model="claude-sonnet-4-6",
        metadata={"agent_id": "test:agent-family-lock"},
        tools=True,
    )
    assert resp.status_code == 200, resp.text[:300]
    decision = await _last_decision(policy_debug)
    assert decision.get("lock_model_family") is True
    assert "gemini-2.5-flash" not in decision.get("ordered_deployments", [])
    assert "fallback:affinity:family_lock" in decision.get("rules_applied", [])


@pytest.mark.mock
async def test_quota_429_preemptive_deprioritizes_credentials(client, policy_debug, mock_litellm_router):
    resp = await _chat(
        client,
        model="claude-sonnet-4-6",
        metadata={"agent_id": "test:quota-429-deprioritize"},
    )
    assert resp.status_code == 200, resp.text[:300]
    decision = await _last_decision(policy_debug)
    assert decision.get("quota_aware_mode") is True
    deprioritized = decision.get("deprioritized_credentials") or []
    assert deprioritized == ["cred-hot", "cred-warm"]
    assert "gemini-2.5-flash" not in decision.get("ordered_deployments", [])
    assert decision.get("ordered_deployments") == ["claude-sonnet-4-6", "gpt-5.5"]
    rules = decision.get("rules_applied", [])
    assert "mock:rate_limit:preemptive" in rules
    assert "fallback:rate_limit:cooldown_skip" in rules

    trace = await _policy_trace(client)
    last = trace.get("last_decision", {})
    assert last.get("quota_aware_mode") is True
    assert last.get("deprioritized_credentials") == ["cred-hot", "cred-warm"]


@pytest.mark.mock
async def test_quota_429_preemptive_from_translator_rate_limit_signals(client, policy_debug, mock_litellm_router):
    # Mocking logic moved to conftest.py _chat_completion_mock side effect
    
    seed = await _chat(
        client,
        model="claude-sonnet-4-6",
        metadata={"agent_id": "test:seed-429-counter"},
        content=f"test:seed-429-counter:{uuid.uuid4().hex}",
    )
    assert seed.status_code == 429, seed.text[:300]

    resp = await _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "composer-follow-up"})
    assert resp.status_code == 200, resp.text[:300]

    context = await _last_context(policy_debug)
    rate_limits = context.get("rate_limits") or []
    assert any(
        isinstance(rl, dict) and rl.get("pre_emptive_degraded") for rl in rate_limits
    ), f"expected pre_emptive_degraded rate_limits in context, got {rate_limits}"

    decision = await _last_decision(policy_debug)
    assert decision.get("quota_aware_mode") is True
    assert "cred-hot" in (decision.get("deprioritized_credentials") or [])
    assert "gemini-2.5-flash" not in decision.get("ordered_deployments", [])
    assert "mock:rate_limit:preemptive" in decision.get("rules_applied", [])


@pytest.mark.mock
async def test_repo_allowlist_restricts_ordered_deployments(client, policy_debug, mock_litellm_router):
    resp = await _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:repo-allowlist"})
    assert resp.status_code == 200, resp.text[:300]
    assert (await _last_decision(policy_debug)).get("ordered_deployments") == ["claude-sonnet-4-6"]


@pytest.mark.mock
async def test_repo_denylist_gate(client, policy_debug, mock_litellm_router):
    resp = await _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:repo-denylist"})
    assert resp.status_code == 200, resp.text[:300]
    decision = await _last_decision(policy_debug)
    assert decision.get("gate") == "deny"
    assert decision.get("deny_reason") == "repo denylist"
    assert decision.get("ordered_deployments") == []


@pytest.mark.mock
async def test_budget_deny_hard_gate_with_retry_after(client, policy_debug, mock_litellm_router):
    resp = await _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:budget-deny"})
    assert resp.status_code == 200, resp.text[:300]
    decision = await _last_decision(policy_debug)
    assert decision.get("gate") == "deny"
    assert decision.get("deny_reason") == "budget exhausted"
    assert decision.get("retry_after_seconds") == 60
    assert "mock:budget:hard_deny" in decision.get("rules_applied", [])
    assert decision.get("quota_aware_mode") is False

    trace = await _policy_trace(client)
    last = trace.get("last_decision", {})
    assert last.get("gate") == "deny"
    assert "deprioritized_credentials" not in last


@pytest.mark.mock
async def test_cooldown_skip_removes_degraded_fallback(client, policy_debug, mock_litellm_router):
    resp = await _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:cooldown-skip"})
    assert resp.status_code == 200, resp.text[:300]
    decision = await _last_decision(policy_debug)
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
async def test_inventory_exclude_deprioritizes_degraded_credentials(client, policy_debug, mock_litellm_router):
    resp = await _chat(
        client,
        model="claude-sonnet-4-6",
        metadata={"agent_id": "test:inventory-exclude"},
    )
    assert resp.status_code == 200, resp.text[:300]
    decision = await _last_decision(policy_debug)
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

    trace = await _policy_trace(client)
    last = trace.get("last_decision", {})
    assert last.get("deprioritized_credentials") == ["cred-degraded"]


@pytest.mark.mock
async def test_admin_status_reports_policy_engine_enabled(client, mock_litellm_router):
    resp = await client.get("/admin/status")
    assert resp.status_code == 200
    routing = resp.json().get("panels", {}).get("routing", {})
    assert routing.get("data", {}).get("policy_engine_enabled") is True
