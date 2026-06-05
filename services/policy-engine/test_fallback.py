"""Unit tests for layered fallback evaluator (issue 38-8)."""

from evaluator.fallback import evaluate_fallback_layers, load_yaml_baseline
from main import evaluate
from profile_store import ProfileStore
from schemas import (
    BudgetSnapshot,
    EvaluateRequest,
    PolicyProfile,
    PolicyScope,
    RateLimitSnapshot,
    RequestCapabilities,
    RoutingContext,
    TenancyContext,
)


def test_capability_filter_removes_non_tool_models():
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6", "gpt-oss-120b-medium", "gemini-3-flash"],
        policy_fallback=["gpt-oss-120b-medium", "gemini-3-flash"],
        capabilities=RequestCapabilities(has_tools=True),
        baseline_path="",
    )
    assert "gpt-oss-120b-medium" not in result.ordered_deployments
    assert "gemini-3-flash" in result.ordered_deployments
    assert "fallback:capability:filter_tools" in result.rules_applied


def test_policy_allowlist_restricts_candidates():
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6"],
        policy_fallback=[],
        capabilities=RequestCapabilities(),
        baseline_path="",
    )
    assert result.ordered_deployments == ["claude-sonnet-4-6"]
    assert "fallback:policy:allowlist" in result.rules_applied


def test_agent_affinity_family_lock_blocks_cross_family_with_tools():
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"],
        policy_fallback=["gemini-3-flash", "gpt-5-4"],
        capabilities=RequestCapabilities(
            has_tools=True,
            active_tool_chain=True,
            model_family="anthropic",
        ),
        agent_affinity={"model_family": "anthropic", "credential_id": "cred-a"},
        baseline_path="",
    )
    assert all(
        m.startswith("claude") or m.endswith("-at-native")
        for m in result.ordered_deployments
        if m != "claude-sonnet-4-6"
    )
    assert "gemini-3-flash" not in result.ordered_deployments
    assert "fallback:affinity:family_lock" in result.rules_applied
    assert result.lock_model_family is True


def test_cooldown_skip_removes_deployments_with_all_creds_unavailable():
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"],
        policy_fallback=["gemini-3-flash", "gpt-5-4"],
        capabilities=RequestCapabilities(),
        rate_limits=[
            RateLimitSnapshot(
                provider="gemini",
                credential_id="cred-g1",
                in_cooldown=True,
            ),
            RateLimitSnapshot(
                provider="gemini",
                credential_id="cred-g2",
                in_cooldown=True,
            ),
        ],
        deployment_credentials={
            "gemini-3-flash": ["cred-g1", "cred-g2"],
            "gpt-5-4": ["cred-o1"],
        },
        baseline_path="",
    )
    assert "gemini-3-flash" not in result.ordered_deployments
    assert "gpt-5-4" in result.ordered_deployments
    assert "fallback:rate_limit:cooldown_skip" in result.rules_applied


def test_health_weighted_order_reorders_tail():
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"],
        policy_fallback=["gemini-3-flash", "gpt-5-4"],
        capabilities=RequestCapabilities(),
        health_scores={
            "gemini-3-flash": 0.9,
            "gpt-5-4": 0.5,
        },
        baseline_path="",
    )
    assert result.ordered_deployments[0] == "claude-sonnet-4-6"
    assert result.ordered_deployments[1:] == ["gemini-3-flash", "gpt-5-4"]
    assert "fallback:health:weighted_order" in result.rules_applied


def test_cost_tier_when_budget_over_80_percent():
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"],
        policy_fallback=["gpt-5-4", "gemini-3-flash"],
        capabilities=RequestCapabilities(),
        budget=BudgetSnapshot(team_budget_pct_used=85.0),
        baseline_path="",
    )
    assert result.ordered_deployments[0] == "claude-sonnet-4-6"
    assert result.ordered_deployments[1:] == ["gemini-3-flash", "gpt-5-4"]
    assert "fallback:budget:cost_tier" in result.rules_applied


def test_yaml_baseline_safety_net_appended():
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"],
        policy_fallback=[],
        capabilities=RequestCapabilities(),
        baseline_path="",
    )
    assert "gemini-3-flash" in result.ordered_deployments
    assert "gpt-5-4" in result.ordered_deployments
    assert "fallback:baseline:yaml" in result.rules_applied


def test_rules_applied_reflect_layer_evaluation_order():
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=[
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "gemini-3-flash",
            "gpt-oss-120b-medium",
        ],
        policy_fallback=["claude-haiku-4-5", "gpt-oss-120b-medium", "gemini-3-flash"],
        capabilities=RequestCapabilities(has_tools=True, active_tool_chain=True, model_family="anthropic"),
        budget=BudgetSnapshot(team_budget_pct_used=90.0),
        health_scores={"claude-haiku-4-5": 0.8},
        baseline_path="",
    )
    tags = result.rules_applied
    assert tags.index("fallback:capability:filter_tools") < tags.index("fallback:policy:allowlist")
    assert tags.index("fallback:policy:allowlist") < tags.index("fallback:affinity:family_lock")
    assert tags.index("fallback:affinity:family_lock") < tags.index("fallback:health:weighted_order")
    assert tags.index("fallback:health:weighted_order") < tags.index("fallback:budget:cost_tier")
    assert tags.index("fallback:budget:cost_tier") < tags.index("fallback:baseline:yaml")


def test_load_yaml_baseline_from_repo_config():
    baseline = load_yaml_baseline("litellm-config.yaml")
    assert "claude-sonnet-4-6" in baseline
    assert "gemini-3-flash" in baseline["claude-sonnet-4-6"]


def test_evaluate_integration_emits_fallback_layer_tags():
    store_profiles = {
        ("repo", "gateway"): PolicyProfile(
            profile_id="prof-gateway",
            scope=PolicyScope.REPO,
            scope_id="gateway",
            allowed_models=["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"],
            fallback_chain_override=["gemini-3-flash", "gpt-5-4"],
        ),
    }
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                tenancy=TenancyContext(repo_name="gateway"),
                capabilities=RequestCapabilities(has_tools=True),
                metadata={
                    "health_scores": {"gemini-3-flash": 0.95, "gpt-5-4": 0.4},
                },
            )
        ),
        profile_store=ProfileStore(None, enabled=False, profiles=store_profiles),
    )
    assert any(r.startswith("fallback:") for r in decision.rules_applied)
    assert decision.ordered_deployments[0] == "claude-sonnet-4-6"
    assert "gemini-3-flash" in decision.ordered_deployments
