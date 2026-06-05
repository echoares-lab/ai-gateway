"""Canned policy-engine for Gate B policy × failover integration tests."""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI

app = FastAPI()
POLICY_VERSION = "mock-gate-b-v1"
_last_evaluate: dict[str, Any] | None = None


def _base_decision(**overrides: Any) -> dict[str, Any]:
    decision = {
        "gate": "allow",
        "allowed_models": ["claude-sonnet-4-6", "gemini-2.5-flash", "gpt-5.5"],
        "fallback_chain": ["gemini-2.5-flash", "gpt-5.5"],
        "ordered_deployments": ["claude-sonnet-4-6", "gemini-2.5-flash", "gpt-5.5"],
        "policy_version": POLICY_VERSION,
        "rules_applied": ["mock:pass_through"],
        "deprioritized_credentials": [],
        "quota_aware_mode": False,
        "lock_model_family": False,
    }
    decision.update(overrides)
    return decision


def _scenario_decision(context: dict[str, Any]) -> dict[str, Any]:
    agent_id = context.get("agent_id") or ""
    tenancy = context.get("tenancy") if isinstance(context.get("tenancy"), dict) else {}
    repo_name = tenancy.get("repo_name")
    caps = context.get("capabilities") if isinstance(context.get("capabilities"), dict) else {}
    rate_limits = context.get("rate_limits") if isinstance(context.get("rate_limits"), list) else []

    if agent_id == "test:agent-family-lock" or (
        agent_id.endswith("agent-family-lock") and caps.get("has_tools")
    ):
        return _base_decision(
            lock_model_family=True,
            ordered_deployments=["claude-sonnet-4-6"],
            fallback_chain=[],
            rules_applied=["mock:agent-family-lock", "fallback:affinity:family_lock"],
        )
    if agent_id == "test:quota-429-deprioritize":
        return _base_decision(
            quota_aware_mode=True,
            deprioritized_credentials=["cred-hot", "cred-warm"],
            ordered_deployments=["claude-sonnet-4-6", "gpt-5.5"],
            rules_applied=["mock:rate_limit:preemptive", "fallback:rate_limit:cooldown_skip"],
        )
    if repo_name == "denied" or agent_id == "test:repo-denylist":
        return _base_decision(
            gate="deny",
            deny_reason="repo denylist",
            allowed_models=[],
            ordered_deployments=[],
            rules_applied=["mock:repo:denylist"],
        )
    if agent_id == "test:budget-deny":
        return _base_decision(
            gate="deny",
            deny_reason="budget exhausted",
            retry_after_seconds=60,
            rules_applied=["mock:budget:hard_deny"],
        )
    if agent_id == "test:cooldown-skip":
        return _base_decision(
            ordered_deployments=["claude-sonnet-4-6", "gpt-5.5"],
            fallback_chain=["gpt-5.5"],
            rules_applied=["mock:cooldown_skip", "fallback:rate_limit:cooldown_skip"],
        )
    if agent_id == "test:inventory-exclude" or any(
        isinstance(rl, dict)
        and rl.get("credential_id") == "cred-degraded"
        and rl.get("in_cooldown")
        for rl in rate_limits
    ):
        return _base_decision(
            quota_aware_mode=True,
            deprioritized_credentials=["cred-degraded"],
            ordered_deployments=["claude-sonnet-4-6", "gpt-5.5"],
            fallback_chain=["gpt-5.5"],
            rules_applied=[
                "mock:inventory:exclude",
                "rate_limit:inventory_cooldown_merged",
                "fallback:rate_limit:cooldown_skip",
            ],
        )
    if agent_id == "test:repo-allowlist":
        return _base_decision(
            allowed_models=["claude-sonnet-4-6"],
            ordered_deployments=["claude-sonnet-4-6"],
            fallback_chain=[],
            rules_applied=["mock:repo:allowlist", "fallback:policy:allowlist"],
        )
    if agent_id == "composer-follow-up" and any(
        rl.get("pre_emptive_degraded") for rl in rate_limits if isinstance(rl, dict)
    ):
        return _base_decision(
            quota_aware_mode=True,
            deprioritized_credentials=["cred-hot", "cred-warm"],
            ordered_deployments=["claude-sonnet-4-6", "gpt-5.5"],
            rules_applied=["mock:rate_limit:preemptive", "fallback:rate_limit:cooldown_skip"],
        )
    return _base_decision()


@app.get("/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "policy_version": POLICY_VERSION}


@app.post("/v1/evaluate")
async def evaluate(body: dict[str, Any]) -> dict[str, Any]:
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    decision = _scenario_decision(context)
    global _last_evaluate
    _last_evaluate = {"context": context, "decision": decision, "evaluated_at": int(time.time())}
    return {"decision": decision}


@app.post("/v1/debug/reset")
def debug_reset() -> dict[str, bool]:
    global _last_evaluate
    _last_evaluate = None
    return {"ok": True}


@app.get("/v1/debug/last")
def debug_last() -> dict[str, Any]:
    return _last_evaluate or {}
