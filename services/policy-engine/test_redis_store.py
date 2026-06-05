"""Unit tests for Redis state store (issue 38-3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from main import evaluate
from redis_store import (
    RedisStateStore,
    agent_affinity_key,
    decision_lkn_key,
    profile_cache_key,
    rate_limit_key,
)
from schemas import EvaluateRequest, RateLimitSnapshot, RoutingContext


@pytest.fixture
def fake_store() -> RedisStateStore:
    client = fakeredis.FakeRedis(decode_responses=True)
    return RedisStateStore(client)


def test_rate_limit_key_pattern():
    assert rate_limit_key("anthropic", "cred-1") == "rate_limit:anthropic:cred-1"


def test_profile_and_decision_key_patterns():
    assert profile_cache_key("repo", "prof-1") == "policy:cache:profile:repo:prof-1"
    assert decision_lkn_key("team-a", "my-repo") == "decision:lkn:team-a:my-repo"


def test_profile_cache_and_decision_lkn_round_trip(fake_store: RedisStateStore):
    fake_store.set_profile_cache("team", "p1", {"allowed_models": ["m1"]})
    fake_store.set_decision_lkn("team-a", "repo-b", {"gate": "allow"})
    assert fake_store.get_profile_cache("team", "p1") == {"allowed_models": ["m1"]}
    assert fake_store.get_decision_lkn("team-a", "repo-b") == {"gate": "allow"}


def test_record_429_increments_rolling_count(fake_store: RedisStateStore):
    now = datetime.now(timezone.utc)
    cooldown = now + timedelta(seconds=120)
    fake_store.record_rate_limit_429("gemini", "cred-a", cooldown_until=cooldown)
    fake_store.record_rate_limit_429("gemini", "cred-a", cooldown_until=cooldown)
    snap = fake_store.rate_limit_to_snapshot("gemini", "cred-a")
    assert snap is not None
    assert snap.rolling_429_count_5m == 2
    assert snap.in_cooldown is True


def test_rate_limit_ttl_matches_cooldown(fake_store: RedisStateStore):
    client = fake_store._client
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=90)
    fake_store.record_rate_limit_429("openai", "cred-b", cooldown_until=cooldown)
    ttl = client.ttl(rate_limit_key("openai", "cred-b"))
    assert 1 <= ttl <= 90


def test_merge_rate_limits_from_redis_merges_cooldown(fake_store: RedisStateStore):
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=60)
    fake_store.record_rate_limit_429("anthropic", "cred-x", cooldown_until=cooldown)
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
    merged = fake_store.merge_rate_limits_from_redis(ctx)
    assert len(merged.rate_limits) == 1
    snap = merged.rate_limits[0]
    assert snap.in_cooldown is True
    assert snap.rolling_429_count_5m >= 1


def test_agent_affinity_round_trip(fake_store: RedisStateStore):
    fake_store.set_agent_affinity("agent-1", credential_id="cred-z", model_family="claude")
    aff = fake_store.get_agent_affinity("agent-1")
    assert aff is not None
    assert aff["credential_id"] == "cred-z"
    assert aff["model_family"] == "claude"
    assert fake_store._client.ttl(agent_affinity_key("agent-1")) > 0


def test_fail_open_without_client():
    store = RedisStateStore(None, enabled=False)
    ctx = RoutingContext(requested_model="m")
    assert store.merge_rate_limits_from_redis(ctx) == ctx
    assert store.record_rate_limit_429("p", "c") is None


def test_apply_credential_cooldown_sets_registry(fake_store: RedisStateStore):
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=45)
    fake_store.apply_credential_cooldown(
        "anthropic",
        "cred-degraded",
        cooldown_until=cooldown,
        status="DEGRADED",
    )
    snap = fake_store.rate_limit_to_snapshot("anthropic", "cred-degraded")
    assert snap is not None
    assert snap.in_cooldown is True
    assert snap.rolling_429_count_5m == 0


def test_evaluate_merges_redis_cooldown_into_decision(fake_store: RedisStateStore):
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=30)
    fake_store.record_rate_limit_429("gemini", "cred-hot", cooldown_until=cooldown)
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="gemini-3-flash",
                rate_limits=[
                    RateLimitSnapshot(provider="gemini", credential_id="cred-hot")
                ],
            )
        ),
        store=fake_store,
    )
    assert "redis:rate_limits_merged" in decision.rules_applied
    assert "cred-hot" in decision.deprioritized_credentials
    assert "rate_limit:cooldown_skip" in decision.rules_applied
