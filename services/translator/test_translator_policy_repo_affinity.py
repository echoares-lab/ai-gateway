"""Unit tests for repo affinity evaluator (issue 38-5)."""

from core.policy.repo_affinity import apply_repo_affinity
from core.policy.evaluate import evaluate
from core.policy.profile_store import ProfileStore
from core.policy.schemas import (
    EvaluateRequest,
    PolicyProfile,
    PolicyScope,
    RoutingContext,
    TenancyContext,
)


def _repo_profile(
    *,
    denied: list[str] | None = None,
    allowed: list[str] | None = None,
    fallback: list[str] | None = None,
    tier: str | None = None,
) -> PolicyProfile:
    return PolicyProfile(
        profile_id="prof-audit-prod",
        scope=PolicyScope.REPO,
        scope_id="audit-prod",
        allowed_models=allowed or [],
        denied_models=denied or [],
        fallback_chain_override=fallback or [],
        credential_tier_preference=tier,
    )


def test_denylist_excludes_models_from_allowed():
    profiles = [_repo_profile(denied=["gpt-5-4", "gemini-3-flash"])]
    allowed, fallback, tier, rules = apply_repo_affinity(
        "claude-sonnet-4-6",
        profiles,
        baseline_allowed=["claude-sonnet-4-6", "gpt-5-4", "gemini-3-flash"],
    )
    assert allowed == ["claude-sonnet-4-6"]
    assert "repo_affinity:repo:audit-prod:denylist" in rules


def test_fallback_chain_override_replaces_static_ordering():
    profiles = [_repo_profile(fallback=["claude-sonnet-4-6", "claude-haiku-4-5"])]
    allowed, fallback, _, rules = apply_repo_affinity("claude-sonnet-4-6", profiles)
    assert fallback == ["claude-sonnet-4-6", "claude-haiku-4-5"]
    assert "repo_affinity:repo:audit-prod:fallback_override" in rules


def test_credential_tier_preference_from_profile():
    profiles = [_repo_profile(tier="native")]
    _, _, tier, rules = apply_repo_affinity("claude-sonnet-4-6", profiles)
    assert tier == "native"
    assert "repo_affinity:repo:audit-prod:tier_preference" in rules


def test_fail_open_when_denylist_blocks_all_models():
    profiles = [_repo_profile(denied=["claude-sonnet-4-6"])]
    allowed, _, _, rules = apply_repo_affinity("claude-sonnet-4-6", profiles)
    assert allowed == ["claude-sonnet-4-6"]
    assert "repo_affinity:fail_open_baseline" in rules


def test_team_then_repo_layered_profiles():
    team = PolicyProfile(
        profile_id="prof-team-eng",
        scope=PolicyScope.TEAM,
        scope_id="eng",
        allowed_models=["claude-sonnet-4-6", "gpt-5-4"],
    )
    repo = PolicyProfile(
        profile_id="prof-gateway",
        scope=PolicyScope.REPO,
        scope_id="gateway",
        denied_models=["gpt-5-4"],
        fallback_chain_override=["claude-sonnet-4-6"],
        credential_tier_preference="antigravity",
    )
    allowed, fallback, tier, rules = apply_repo_affinity(
        "claude-sonnet-4-6",
        [team, repo],
        baseline_allowed=["claude-sonnet-4-6", "gpt-5-4", "gemini-3-flash"],
    )
    assert allowed == ["claude-sonnet-4-6"]
    assert fallback == ["claude-sonnet-4-6"]
    assert tier == "antigravity"
    assert "repo_affinity:team:eng:allowlist" in rules
    assert "repo_affinity:repo:gateway:denylist" in rules


def test_evaluate_applies_repo_profile_from_fixture_store():
    store = ProfileStore(
        None,
        enabled=False,
        profiles={
            ("repo", "audit-prod"): _repo_profile(
                denied=["gpt-5-4"],
                fallback=["claude-sonnet-4-6", "claude-haiku-4-5"],
                tier="native",
            ),
        },
    )
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                tenancy=TenancyContext(repo_name="audit-prod"),
            )
        ),
        profile_store=store,
    )
    assert "repo_affinity:repo:audit-prod:denylist" in decision.rules_applied
    assert decision.fallback_chain == [
        "claude-sonnet-4-6-at-native",
        "claude-haiku-4-5",
    ]
    assert decision.credential_tier_preference == "native"


def test_dry_run_evaluates_profiles_without_state_writes():
    store = ProfileStore(
        None,
        enabled=False,
        profiles={
            ("repo", "gateway"): _repo_profile(denied=["gemini-3-flash"]),
        },
    )
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                tenancy=TenancyContext(repo_name="gateway"),
                dry_run=True,
            )
        ),
        profile_store=store,
    )
    assert "dry_run:no_state_write" in decision.rules_applied
    assert any(rule.startswith("repo_affinity:") for rule in decision.rules_applied)
