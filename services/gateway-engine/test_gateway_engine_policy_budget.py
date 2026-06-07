"""Unit tests for budget gate evaluator (issue 38-9)."""

from core.policy.budget import (
    apply_budget_gates,
    apply_soft_headroom_gates,
    extract_budget_config,
)
from core.policy.evaluate import evaluate
from core.policy.schemas import (
    BudgetSnapshot,
    EvaluateRequest,
    GateAction,
    PolicyProfile,
    PolicyScope,
    QuotaHeadroom,
    RoutingContext,
)


def _profile(
    *,
    scope: PolicyScope = PolicyScope.TEAM,
    scope_id: str = "eng",
    policy_json: dict | None = None,
) -> PolicyProfile:
    return PolicyProfile(
        profile_id=f"prof-{scope_id}",
        scope=scope,
        scope_id=scope_id,
        policy_json=policy_json or {},
    )


def test_soft_deprioritize_below_threshold():
    deprioritized, rules = apply_soft_headroom_gates(
        [
            QuotaHeadroom(credential_id="cred-low", headroom_pct=10.0),
            QuotaHeadroom(credential_id="cred-ok", headroom_pct=50.0),
        ],
        threshold_pct=15.0,
    )
    assert deprioritized == ["cred-low"]
    assert "budget:soft_deprioritize" in rules


def test_soft_deprioritize_respects_below_soft_threshold_flag():
    deprioritized, rules = apply_soft_headroom_gates(
        [QuotaHeadroom(credential_id="cred-flagged", below_soft_threshold=True)],
        threshold_pct=15.0,
    )
    assert deprioritized == ["cred-flagged"]
    assert "budget:soft_deprioritize" in rules


def test_threshold_configurable_via_policy_json():
    profiles = [
        _profile(
            policy_json={"budget": {"soft_gate_threshold_pct": 25}},
        )
    ]
    config = extract_budget_config(profiles)
    assert config.soft_gate_threshold_pct == 25.0

    deprioritized, _ = apply_soft_headroom_gates(
        [QuotaHeadroom(credential_id="cred-mid", headroom_pct=20.0)],
        threshold_pct=config.soft_gate_threshold_pct,
    )
    assert deprioritized == ["cred-mid"]


def test_hard_deny_when_budget_exhausted_and_enabled():
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        budget=BudgetSnapshot(team_budget_pct_used=100.0),
    )
    result = apply_budget_gates(ctx, [], hard_gate_enabled=True)
    assert result.gate == GateAction.DENY
    assert result.deny_reason is not None
    assert result.retry_after_seconds == 60
    assert "budget:hard_deny" in result.rules_applied


def test_hard_deny_fail_open_when_disabled():
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        budget=BudgetSnapshot(team_budget_pct_used=100.0),
    )
    result = apply_budget_gates(ctx, [], hard_gate_enabled=False)
    assert result.gate == GateAction.ALLOW
    assert result.deny_reason is None
    assert "budget:hard_deny_skipped_fail_open" in result.rules_applied


def test_hard_deny_rpm_exhausted():
    ctx = RoutingContext(
        requested_model="gpt-5-4",
        budget=BudgetSnapshot(rpm_remaining=0),
    )
    result = apply_budget_gates(ctx, [], hard_gate_enabled=True)
    assert result.gate == GateAction.DENY
    assert "RPM" in (result.deny_reason or "")


def test_cost_tier_preference_when_budget_pressure_high():
    profiles = [
        _profile(
            policy_json={
                "budget": {
                    "cost_tier_threshold_pct": 80,
                    "cost_tier_preference": "economy",
                }
            }
        )
    ]
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        budget=BudgetSnapshot(team_budget_pct_used=85.0),
    )
    result = apply_budget_gates(ctx, profiles, hard_gate_enabled=False)
    assert result.credential_tier_preference == "economy"
    assert "budget:cost_tier_preference" in result.rules_applied


def test_evaluate_integrates_budget_soft_and_hard_fail_open():
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="gpt-5-4",
                budget=BudgetSnapshot(team_budget_pct_used=100.0),
                quota_headroom=[
                    QuotaHeadroom(
                        credential_id="cred-low",
                        headroom_pct=5.0,
                    )
                ],
            )
        )
    )
    assert decision.gate == GateAction.ALLOW
    assert "cred-low" in decision.deprioritized_credentials
    assert "budget:soft_deprioritize" in decision.rules_applied
    assert "budget:hard_deny_skipped_fail_open" in decision.rules_applied


def test_evaluate_hard_deny_when_profile_enables_gate():
    from core.policy.profile_store import ProfileStore
    from core.policy.schemas import TenancyContext

    store = ProfileStore(
        None,
        enabled=False,
        profiles={
            ("team", "eng"): _profile(
                policy_json={"budget": {"hard_gate_enabled": True}},
            ),
        },
    )
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                tenancy=TenancyContext(team_id="eng"),
                budget=BudgetSnapshot(team_budget_pct_used=100.0),
            )
        ),
        profile_store=store,
    )
    assert decision.gate == GateAction.DENY
    assert decision.deny_reason is not None
    assert decision.retry_after_seconds == 60
    assert "budget:hard_deny" in decision.rules_applied
