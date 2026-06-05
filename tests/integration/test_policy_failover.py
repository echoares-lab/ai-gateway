"""Policy × failover integration tests (issue 38-17, Gate B)."""

from __future__ import annotations

import os

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


def _chat(client: httpx.Client, *, model: str, metadata: dict | None = None, tools: bool = False):
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
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


def _last_decision(policy_engine: httpx.Client) -> dict:
    payload = policy_engine.get("/v1/debug/last").json()
    assert payload, "policy-engine received no /v1/evaluate call"
    decision = payload.get("decision")
    assert isinstance(decision, dict), f"unexpected debug payload: {payload}"
    return decision


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
def test_quota_429_fixture_deprioritizes_credentials(client, policy_engine):
    resp = _chat(
        client,
        model="claude-sonnet-4-6",
        metadata={"agent_id": "test:quota-429-deprioritize"},
    )
    assert resp.status_code == 200, resp.text[:300]
    decision = _last_decision(policy_engine)
    assert decision.get("quota_aware_mode") is True
    assert "cred-hot" in (decision.get("deprioritized_credentials") or [])


@pytest.mark.mock
def test_repo_allowlist_restricts_ordered_deployments(client, policy_engine):
    resp = _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:repo-allowlist"})
    assert resp.status_code == 200, resp.text[:300]
    assert _last_decision(policy_engine).get("ordered_deployments") == ["claude-sonnet-4-6"]


@pytest.mark.mock
def test_repo_denylist_gate(client, policy_engine):
    resp = _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:repo-denylist"})
    assert resp.status_code == 200, resp.text[:300]
    assert _last_decision(policy_engine).get("gate") == "deny"


@pytest.mark.mock
def test_budget_deny_gate(client, policy_engine):
    resp = _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:budget-deny"})
    assert resp.status_code == 200, resp.text[:300]
    decision = _last_decision(policy_engine)
    assert decision.get("gate") == "deny"
    assert decision.get("retry_after_seconds") == 60


@pytest.mark.mock
def test_cooldown_skip_shifts_fallback_chain(client, policy_engine):
    resp = _chat(client, model="claude-sonnet-4-6", metadata={"agent_id": "test:cooldown-skip"})
    assert resp.status_code == 200, resp.text[:300]
    decision = _last_decision(policy_engine)
    assert "gemini-2.5-flash" not in decision.get("ordered_deployments", [])
    assert "gpt-5.5" in decision.get("ordered_deployments", [])


@pytest.mark.mock
def test_admin_status_reports_policy_engine_enabled(client):
    resp = client.get("/admin/status")
    assert resp.status_code == 200
    routing = resp.json().get("panels", {}).get("routing", {})
    assert routing.get("data", {}).get("policy_engine_enabled") is True
