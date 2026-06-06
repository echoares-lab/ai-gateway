"""Unit tests for agent affinity evaluator (issue 38-6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import fakeredis
import pytest

from core.policy.agent_affinity import (
    apply_agent_affinity,
    build_session_key,
    should_lock_model_family,
)
from core.policy.evaluate import evaluate
from core.policy.redis_store import RedisStateStore, agent_affinity_key
from core.policy.schemas import (
    EvaluateRequest,
    RateLimitSnapshot,
    RequestCapabilities,
    RoutingContext,
)


@pytest.fixture
def fake_store() -> RedisStateStore:
    client = fakeredis.FakeRedis(decode_responses=True)
    return RedisStateStore(client)


def test_build_session_key_with_agent_only():
    ctx = RoutingContext(requested_model="m", agent_id="composer-1")
    assert build_session_key(ctx) == "agent:composer-1"


def test_build_session_key_includes_session_id():
    ctx = RoutingContext(
        requested_model="m",
        agent_id="composer-1",
        session_id="sess-abc",
    )
    assert build_session_key(ctx) == "agent:composer-1:sess-abc"


def test_lock_model_family_when_tools_and_active_chain():
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        capabilities=RequestCapabilities(
            has_tools=True,
            active_tool_chain=True,
            model_family="claude",
        ),
    )
    assert should_lock_model_family(ctx) is True


def test_no_lock_without_active_tool_chain():
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        capabilities=RequestCapabilities(has_tools=True, active_tool_chain=False),
    )
    assert should_lock_model_family(ctx) is False


def test_sticky_hit_returns_preferred_credential(fake_store: RedisStateStore):
    fake_store.set_agent_affinity("agent-42", credential_id="cred-sticky", model_family="claude")
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        agent_id="agent-42",
    )
    preferred, session_key, lock_family, cold_start, tier, rules = apply_agent_affinity(
        ctx,
        fake_store,
        deprioritized_credentials=[],
    )
    assert preferred == "cred-sticky"
    assert session_key == "agent:agent-42"
    assert cold_start is False
    assert "agent_affinity:sticky_hit" in rules
    assert fake_store.get_agent_affinity("agent-42")["credential_id"] == "cred-sticky"


def test_429_on_bound_credential_rebinds_and_sets_cold_start(fake_store: RedisStateStore):
    fake_store.set_agent_affinity("agent-hot", credential_id="cred-exhausted", model_family="gemini")
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=120)
    ctx = RoutingContext(
        requested_model="gemini-3-flash",
        agent_id="agent-hot",
        metadata={"credential_id": "cred-fresh", "credential_candidates": ["cred-fresh"]},
        rate_limits=[
            RateLimitSnapshot(
                provider="gemini",
                credential_id="cred-exhausted",
                in_cooldown=True,
                cooldown_until=cooldown,
            )
        ],
    )
    preferred, _, _, cold_start, _, rules = apply_agent_affinity(
        ctx,
        fake_store,
        deprioritized_credentials=["cred-exhausted"],
    )
    assert cold_start is True
    assert preferred == "cred-fresh"
    assert "agent_affinity:rebind_429" in rules
    assert "agent_affinity:bind" in rules
    assert fake_store.get_agent_affinity("agent-hot")["credential_id"] == "cred-fresh"


def test_lock_model_family_in_evaluate_with_tools(fake_store: RedisStateStore):
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                agent_id="tool-agent",
                capabilities=RequestCapabilities(
                    has_tools=True,
                    active_tool_chain=True,
                    model_family="claude",
                ),
                metadata={"credential_id": "cred-a"},
            )
        ),
        store=fake_store,
    )
    assert decision.lock_model_family is True
    assert decision.session_key == "agent:tool-agent"
    assert any(rule.startswith("agent_affinity:") for rule in decision.rules_applied)
    assert "agent_affinity:lock_model_family" in decision.rules_applied


def test_evaluate_sticky_within_ttl(fake_store: RedisStateStore):
    fake_store.set_agent_affinity("sticky-agent", credential_id="cred-z", model_family="claude")
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                agent_id="sticky-agent",
            )
        ),
        store=fake_store,
    )
    assert decision.preferred_credential_id == "cred-z"
    assert "agent_affinity:sticky_hit" in decision.rules_applied
    assert fake_store._client.ttl(agent_affinity_key("sticky-agent")) > 0


def test_background_agent_pool_sets_lower_tier(fake_store: RedisStateStore):
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                agent_id="bg-worker",
                metadata={"agent_pool": "background", "credential_id": "cred-bg"},
            )
        ),
        store=fake_store,
    )
    assert decision.credential_tier_preference == "antigravity"
    assert "agent_affinity:pool_background" in decision.rules_applied


def test_interactive_agent_pool_sets_premium_tier(fake_store: RedisStateStore):
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                agent_id="ui-agent",
                metadata={"agent_pool": "interactive", "credential_id": "cred-ui"},
            )
        ),
        store=fake_store,
    )
    assert decision.credential_tier_preference == "native"
    assert "agent_affinity:pool_interactive" in decision.rules_applied


def test_dry_run_skips_affinity_writes(fake_store: RedisStateStore):
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="claude-sonnet-4-6",
                agent_id="dry-agent",
                metadata={"credential_id": "cred-new"},
                dry_run=True,
            )
        ),
        store=fake_store,
    )
    assert "agent_affinity:bind" in decision.rules_applied
    assert fake_store.get_agent_affinity("dry-agent") is None


def test_evaluate_429_rebind_sets_cache_cold_start(fake_store: RedisStateStore):
    fake_store.set_agent_affinity("rebind-agent", credential_id="cred-old", model_family="gemini")
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=60)
    fake_store.record_rate_limit_429("gemini", "cred-old", cooldown_until=cooldown)
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="gemini-3-flash",
                agent_id="rebind-agent",
                metadata={"credential_id": "cred-new"},
                rate_limits=[
                    RateLimitSnapshot(provider="gemini", credential_id="cred-old")
                ],
            )
        ),
        store=fake_store,
    )
    assert decision.cache_cold_start is True
    assert decision.preferred_credential_id == "cred-new"
    assert "agent_affinity:rebind_429" in decision.rules_applied
    assert fake_store.get_agent_affinity("rebind-agent")["credential_id"] == "cred-new"
