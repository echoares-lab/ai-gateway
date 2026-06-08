"""Unit tests for rate-limit aggregator (issue 38-7)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.policy.evaluate import evaluate
from core.policy.inventory_store import InventoryStore
from core.policy.rate_limit import (
    aggregate_and_evaluate,
    evaluate_rate_limits,
    merge_rate_limit_sources,
    resolve_preemptive_threshold,
)
from core.policy.redis_store import RedisStateStore
from core.policy.schemas import (
    EvaluateRequest,
    PolicyProfile,
    PolicyScope,
    RateLimitSnapshot,
    RoutingContext,
)


def test_merge_gateway_engine_and_redis_rolling_counts(redis_state_store: RedisStateStore):
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=60)
    redis_state_store.record_rate_limit_429("anthropic", "cred-x", cooldown_until=cooldown)
    redis_state_store.record_rate_limit_429("anthropic", "cred-x", cooldown_until=cooldown)
    redis_state_store.record_rate_limit_429("anthropic", "cred-x", cooldown_until=cooldown)

    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        rate_limits=[
            RateLimitSnapshot(
                provider="anthropic",
                credential_id="cred-x",
                rolling_429_count_5m=1,
            )
        ],
    )
    merged, rules = merge_rate_limit_sources(ctx, redis_store=redis_state_store)
    assert "rate_limit:gateway_engine_signals_merged" in rules
    assert "redis:rate_limits_merged" in rules
    snap = merged.rate_limits[0]
    assert snap.rolling_429_count_5m == 3
    assert snap.in_cooldown is True


def test_merge_inventory_cool_down_until():
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    inventory = InventoryStore(
        None,
        enabled=False,
        fixtures={"cred-inv": ("gemini", future)},
    )
    ctx = RoutingContext(
        requested_model="gemini-3-flash",
        rate_limits=[RateLimitSnapshot(provider="gemini", credential_id="cred-inv")],
    )
    merged, rules = merge_rate_limit_sources(ctx, inventory_store=inventory)
    assert "rate_limit:inventory_routing_merged" in rules
    assert "rate_limit:inventory_status_excluded" in rules
    snap = merged.rate_limits[0]
    assert snap.in_cooldown is True
    assert snap.cooldown_until == future


def test_preemptive_deprioritize_above_threshold():
    ctx = RoutingContext(
        requested_model="gemini-3-flash",
        rate_limits=[
            RateLimitSnapshot(
                provider="gemini",
                credential_id="cred-hot",
                rolling_429_count_5m=4,
            )
        ],
    )
    result = evaluate_rate_limits(ctx, threshold=3)
    assert "cred-hot" in result.deprioritized_credentials
    assert "rate_limit:preemptive_deprioritize" in result.rules_applied
    assert result.merged_rate_limits[0].pre_emptive_degraded is True


def test_quota_aware_mode_from_pool_affinity_only():
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        pool_affinity_mode="quota-aware",
    )
    result = evaluate_rate_limits(ctx)
    assert result.quota_aware_mode is True
    assert "pool:quota_aware_mode" in result.rules_applied
    assert result.deprioritized_credentials == []


def test_quota_aware_mode_when_deprioritized_without_pool_mode():
    ctx = RoutingContext(
        requested_model="gemini-3-flash",
        rate_limits=[
            RateLimitSnapshot(
                provider="gemini",
                credential_id="cred-a",
                rolling_429_count_5m=5,
            )
        ],
    )
    result = evaluate_rate_limits(ctx, threshold=3)
    assert result.quota_aware_mode is True


def test_resolve_threshold_from_policy_json():
    profiles = [
        PolicyProfile(
            profile_id="p1",
            scope=PolicyScope.REPO,
            scope_id="r1",
            policy_json={"rate_limit": {"preemptive_429_threshold": 7}},
        )
    ]
    assert resolve_preemptive_threshold(profiles, default=3) == 7


def test_skip_models_when_all_backing_credentials_cooled():
    future = datetime.now(timezone.utc) + timedelta(minutes=2)
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        rate_limits=[
            RateLimitSnapshot(
                provider="anthropic",
                credential_id="cred-1",
                in_cooldown=True,
                cooldown_until=future,
            ),
            RateLimitSnapshot(
                provider="anthropic",
                credential_id="cred-2",
                in_cooldown=True,
                cooldown_until=future,
            ),
        ],
        metadata={
            "backing_credentials": {
                "claude-sonnet-4-6": ["cred-1", "cred-2"],
                "claude-haiku-4-5": ["cred-3"],
            }
        },
    )
    result = evaluate_rate_limits(ctx)
    assert "claude-sonnet-4-6" in result.skipped_models
    assert "claude-haiku-4-5" not in result.skipped_models
    assert "rate_limit:skip_all_cooled_models" in result.rules_applied


def test_aggregate_and_evaluate_end_to_end(redis_state_store: RedisStateStore):
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=45)
    redis_state_store.record_rate_limit_429("openai", "cred-o", cooldown_until=cooldown)
    inventory = InventoryStore(
        None,
        enabled=False,
        fixtures={"cred-o": ("openai", cooldown)},
    )
    ctx = RoutingContext(
        requested_model="gpt-5-4",
        rate_limits=[RateLimitSnapshot(provider="openai", credential_id="cred-o", rolling_429_count_5m=1)],
        pool_affinity_mode="quota-aware",
    )
    _, evaluation, merge_rules = aggregate_and_evaluate(
        ctx,
        redis_store=redis_state_store,
        inventory_store=inventory,
    )
    assert "rate_limit:gateway_engine_signals_merged" in merge_rules
    assert "cred-o" in evaluation.deprioritized_credentials
    assert evaluation.quota_aware_mode is True


def test_inventory_critical_status_deprioritized():
    inventory = InventoryStore(None, enabled=False, fixtures={"cred-critical": ("anthropic", None, "CRITICAL")})
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        rate_limits=[RateLimitSnapshot(provider="anthropic", credential_id="cred-critical")],
    )
    _, evaluation, merge_rules = aggregate_and_evaluate(ctx, inventory_store=inventory)
    assert "rate_limit:inventory_status_excluded" in merge_rules
    assert "cred-critical" in evaluation.deprioritized_credentials


def test_evaluate_wires_aggregator_with_inventory_and_redis(redis_state_store: RedisStateStore):
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=30)
    redis_state_store.record_rate_limit_429("gemini", "cred-hot", cooldown_until=cooldown)
    inventory = InventoryStore(
        None,
        enabled=False,
        fixtures={"cred-hot": ("gemini", cooldown)},
    )
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="gemini-3-flash",
                rate_limits=[RateLimitSnapshot(provider="gemini", credential_id="cred-hot")],
            )
        ),
        store=redis_state_store,
        inventory_store=inventory,
    )
    assert "rate_limit:inventory_routing_merged" in decision.rules_applied
    assert "redis:rate_limits_merged" in decision.rules_applied
    assert "cred-hot" in decision.deprioritized_credentials
    assert "rate_limit:cooldown_skip" in decision.rules_applied
