"""Unit tests for eval-quality reorder layer (issue 38-19 Phase 5b)."""

from evaluator.fallback import evaluate_fallback_layers
from evaluator.quality import (
    RULE_TAG,
    apply_quality_reorder,
    extract_eval_config,
    resolve_task_category,
)
from main import evaluate
from profile_store import ProfileStore
from schemas import (
    EvaluateRequest,
    PolicyProfile,
    PolicyScope,
    RequestCapabilities,
    RoutingContext,
    TenancyContext,
)


def _profile_with_eval(
    *,
    allowed_models: list[str] | None = None,
    fallback_chain_override: list[str] | None = None,
    **eval_section,
) -> PolicyProfile:
    return PolicyProfile(
        profile_id="prof-eval",
        scope=PolicyScope.REPO,
        scope_id="gateway",
        allowed_models=allowed_models or [],
        fallback_chain_override=fallback_chain_override or [],
        policy_json={"eval": eval_section},
    )


def test_extract_eval_config_defaults_disabled():
    config = extract_eval_config([])
    assert config.enabled is False
    assert config.weight_blend == 0.3
    assert config.model_scores == {}


def test_extract_eval_config_merges_profile_section():
    config = extract_eval_config(
        [
            _profile_with_eval(
                enabled=True,
                weight_blend=0.5,
                model_scores={
                    "code_edit": {"claude-sonnet-4-6": 0.92, "gpt-5-4": 0.88},
                },
            )
        ]
    )
    assert config.enabled is True
    assert config.weight_blend == 0.5
    assert config.model_scores["code_edit"]["gpt-5-4"] == 0.88


def test_resolve_task_category_from_metadata_overrides_profile():
    config = extract_eval_config([_profile_with_eval(task_category="summarization")])
    assert resolve_task_category(config, {"task_category": "code_edit"}) == "code_edit"


def test_resolve_task_category_defaults_to_chat():
    config = extract_eval_config([_profile_with_eval(task_category="auto")])
    assert resolve_task_category(config, {}) == "chat"


def test_apply_quality_reorder_disabled_is_noop():
    result = apply_quality_reorder(
        ["claude-sonnet-4-6", "gpt-5-4", "gemini-3-flash"],
        requested_model="claude-sonnet-4-6",
        eval_config=extract_eval_config([]),
        task_category="chat",
    )
    assert result.applied is False
    assert result.rules_applied == []
    assert result.candidates == ["claude-sonnet-4-6", "gpt-5-4", "gemini-3-flash"]


def test_apply_quality_reorder_fail_open_without_category_scores():
    config = extract_eval_config([_profile_with_eval(enabled=True, model_scores={"chat": {}})])
    result = apply_quality_reorder(
        ["claude-sonnet-4-6", "gpt-5-4"],
        requested_model="claude-sonnet-4-6",
        eval_config=config,
        task_category="code_edit",
    )
    assert result.applied is False


def test_apply_quality_reorder_sorts_tail_by_quality_scores():
    config = extract_eval_config(
        [
            _profile_with_eval(
                enabled=True,
                weight_blend=1.0,
                model_scores={
                    "chat": {
                        "gemini-3-flash": 0.95,
                        "gpt-5-4": 0.5,
                    },
                },
            )
        ]
    )
    result = apply_quality_reorder(
        ["claude-sonnet-4-6", "gpt-5-4", "gemini-3-flash"],
        requested_model="claude-sonnet-4-6",
        eval_config=config,
        task_category="chat",
    )
    assert result.applied is True
    assert result.rules_applied == [RULE_TAG]
    assert result.candidates == ["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"]


def test_fallback_layer_eval_runs_between_health_and_cost_tier():
    profiles = [
        _profile_with_eval(
            enabled=True,
            weight_blend=1.0,
            model_scores={
                "chat": {
                    "gemini-3-flash": 0.99,
                    "gpt-5-4": 0.1,
                },
            },
        )
    ]
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"],
        policy_fallback=["gpt-5-4", "gemini-3-flash"],
        capabilities=RequestCapabilities(),
        health_scores={"gpt-5-4": 0.99, "gemini-3-flash": 0.1},
        policy_profiles=profiles,
        baseline_path="",
    )
    tags = result.rules_applied
    assert RULE_TAG in tags
    assert result.ordered_deployments[1:] == ["gemini-3-flash", "gpt-5-4"]
    assert tags.index("fallback:health:weighted_order") < tags.index(RULE_TAG)
    assert tags.index(RULE_TAG) < tags.index("fallback:baseline:yaml")


def test_fallback_skips_eval_when_disabled_by_default():
    result = evaluate_fallback_layers(
        "claude-sonnet-4-6",
        allowed_models=["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"],
        policy_fallback=["gpt-5-4", "gemini-3-flash"],
        capabilities=RequestCapabilities(),
        health_scores={"gpt-5-4": 0.1, "gemini-3-flash": 0.99},
        policy_profiles=[
            PolicyProfile(
                profile_id="prof-no-eval",
                scope=PolicyScope.REPO,
                scope_id="gateway",
                policy_json={},
            )
        ],
        baseline_path="",
    )
    assert RULE_TAG not in result.rules_applied
    assert result.ordered_deployments[1:] == ["gemini-3-flash", "gpt-5-4"]


def test_evaluate_integration_emits_eval_quality_tag():
    store_profiles = {
        ("repo", "gateway"): _profile_with_eval(
            allowed_models=["claude-sonnet-4-6", "gemini-3-flash", "gpt-5-4"],
            fallback_chain_override=["gemini-3-flash", "gpt-5-4"],
            enabled=True,
            weight_blend=1.0,
            model_scores={
                "code_edit": {
                    "gemini-3-flash": 0.95,
                    "gpt-5-4": 0.4,
                },
            },
        ),
    }
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                tenancy=TenancyContext(repo_name="gateway"),
                capabilities=RequestCapabilities(),
                metadata={
                    "task_category": "code_edit",
                    "health_scores": {"gemini-3-flash": 0.1, "gpt-5-4": 0.99},
                },
            )
        ),
        profile_store=ProfileStore(None, enabled=False, profiles=store_profiles),
    )
    assert RULE_TAG in decision.rules_applied
    assert decision.ordered_deployments[1:][0] == "gemini-3-flash"
