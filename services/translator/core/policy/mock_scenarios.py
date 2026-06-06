"""Canned routing decisions for Gate B mock integration (mirrors tests/mock-policy-engine)."""

from __future__ import annotations

from typing import Any

POLICY_VERSION = "mock-gate-b-v1"
_last_evaluate: dict[str, Any] | None = None


def reset_mock_scenarios() -> None:
    global _last_evaluate
    _last_evaluate = None


def last_evaluate_payload() -> dict[str, Any] | None:
    return _last_evaluate


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


def evaluate_mock_scenario(context: dict[str, Any]) -> dict[str, Any]:
    """Return a canned RoutingDecision dict for mock-tier integration tests."""
    global _last_evaluate
    agent_id = context.get("agent_id") or ""
    tenancy = context.get("tenancy") if isinstance(context.get("tenancy"), dict) else {}
    repo_name = tenancy.get("repo_name")
    caps = context.get("capabilities") if isinstance(context.get("capabilities"), dict) else {}
    rate_limits = context.get("rate_limits") if isinstance(context.get("rate_limits"), list) else []

    if agent_id == "test:agent-family-lock" or (
        agent_id.endswith("agent-family-lock") and caps.get("has_tools")
    ):
        decision = _base_decision(
            lock_model_family=True,
            ordered_deployments=["claude-sonnet-4-6"],
            fallback_chain=[],
            rules_applied=["mock:agent-family-lock", "fallback:affinity:family_lock"],
        )
    elif agent_id == "test:quota-429-deprioritize":
        decision = _base_decision(
            quota_aware_mode=True,
            deprioritized_credentials=["cred-hot", "cred-warm"],
            ordered_deployments=["claude-sonnet-4-6", "gpt-5.5"],
            rules_applied=["mock:rate_limit:preemptive", "fallback:rate_limit:cooldown_skip"],
        )
    elif repo_name == "denied" or agent_id == "test:repo-denylist":
        decision = _base_decision(
            gate="deny",
            deny_reason="repo denylist",
            allowed_models=[],
            ordered_deployments=[],
            rules_applied=["mock:repo:denylist"],
        )
    elif agent_id == "test:budget-deny":
        decision = _base_decision(
            gate="deny",
            deny_reason="budget exhausted",
            retry_after_seconds=60,
            rules_applied=["mock:budget:hard_deny"],
        )
    elif agent_id == "test:cooldown-skip":
        decision = _base_decision(
            ordered_deployments=["claude-sonnet-4-6", "gpt-5.5"],
            fallback_chain=["gpt-5.5"],
            rules_applied=["mock:cooldown_skip", "fallback:rate_limit:cooldown_skip"],
        )
    elif agent_id == "test:inventory-exclude" or any(
        isinstance(rl, dict) and rl.get("credential_id") == "cred-degraded" and rl.get("in_cooldown")
        for rl in rate_limits
    ):
        decision = _base_decision(
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
    elif agent_id == "test:repo-allowlist":
        decision = _base_decision(
            allowed_models=["claude-sonnet-4-6"],
            ordered_deployments=["claude-sonnet-4-6"],
            fallback_chain=[],
            rules_applied=["mock:repo:allowlist", "fallback:policy:allowlist"],
        )
    elif agent_id == "composer-follow-up" and any(
        rl.get("pre_emptive_degraded") for rl in rate_limits if isinstance(rl, dict)
    ):
        decision = _base_decision(
            quota_aware_mode=True,
            deprioritized_credentials=["cred-hot", "cred-warm"],
            ordered_deployments=["claude-sonnet-4-6", "gpt-5.5"],
            rules_applied=["mock:rate_limit:preemptive", "fallback:rate_limit:cooldown_skip"],
        )
    else:
        decision = _base_decision()

    _last_evaluate = {"context": context, "decision": decision}
    return decision
