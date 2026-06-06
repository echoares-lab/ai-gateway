"""Unit tests for credential event handler (issue 38-12, ported to translator)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
from core.policy.credential_events import handle_credential_event
from core.policy.evaluate import evaluate
from core.policy.redis_store import RedisStateStore, rate_limit_key
from core.policy.schemas import CredentialEvent, EvaluateRequest, RateLimitSnapshot, RoutingContext


@pytest.fixture
def fake_store() -> RedisStateStore:
    client = fakeredis.FakeRedis(decode_responses=True)
    return RedisStateStore(client)


def test_degraded_event_sets_cooldown(fake_store: RedisStateStore):
    event = CredentialEvent(
        credential_id="cred-1",
        provider="anthropic",
        previous_status="HEALTHY",
        new_status="DEGRADED",
        reason="upstream timeout",
    )
    assert handle_credential_event(event, fake_store) is True
    snap = fake_store.rate_limit_to_snapshot("anthropic", "cred-1")
    assert snap is not None
    assert snap.in_cooldown is True


def test_rate_limited_event_increments_rolling_count(fake_store: RedisStateStore):
    event = CredentialEvent(
        credential_id="cred-2",
        provider="gemini",
        previous_status="HEALTHY",
        new_status="RATE_LIMITED",
        reason="429 Too Many Requests",
    )
    assert handle_credential_event(event, fake_store) is True
    state = fake_store.get_rate_limit_state("gemini", "cred-2")
    assert state is not None
    assert state["rolling_429_count"] == 1


def test_duplicate_event_is_idempotent(fake_store: RedisStateStore):
    ts = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    event = CredentialEvent(
        credential_id="cred-3",
        provider="openai",
        previous_status="HEALTHY",
        new_status="DEGRADED",
        timestamp=ts,
    )
    handle_credential_event(event, fake_store)
    first = fake_store.get_rate_limit_state("openai", "cred-3")
    handle_credential_event(event, fake_store)
    second = fake_store.get_rate_limit_state("openai", "cred-3")
    assert first == second


def test_critical_event_sets_cooldown(fake_store: RedisStateStore):
    event = CredentialEvent(
        credential_id="cred-4",
        provider="anthropic",
        previous_status="HEALTHY",
        new_status="CRITICAL",
        reason="401 Unauthorized",
    )
    assert handle_credential_event(event, fake_store) is True
    snap = fake_store.rate_limit_to_snapshot("anthropic", "cred-4")
    assert snap is not None
    assert snap.in_cooldown is True


def test_evaluate_reflects_event_cooldown(fake_store: RedisStateStore):
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=120)
    handle_credential_event(
        CredentialEvent(
            credential_id="cred-hot",
            provider="gemini",
            previous_status="HEALTHY",
            new_status="DEGRADED",
            cool_down_until=cooldown,
        ),
        fake_store,
    )
    decision = evaluate(
        EvaluateRequest(
            context=RoutingContext(
                requested_model="gemini-3-flash",
                rate_limits=[RateLimitSnapshot(provider="gemini", credential_id="cred-hot")],
            )
        ),
        store=fake_store,
    )
    assert "cred-hot" in decision.deprioritized_credentials
    assert "rate_limit:cooldown_skip" in decision.rules_applied


def test_suspended_event_sets_long_cooldown(fake_store: RedisStateStore):
    event = CredentialEvent(
        credential_id="cred-susp",
        provider="openai",
        previous_status="HEALTHY",
        new_status="SUSPENDED",
        reason="operator disabled",
    )
    assert handle_credential_event(event, fake_store) is True
    snap = fake_store.rate_limit_to_snapshot("openai", "cred-susp")
    assert snap is not None
    assert snap.in_cooldown is True


def test_healthy_transition_does_not_write_redis(fake_store: RedisStateStore):
    event = CredentialEvent(
        credential_id="cred-5",
        provider="anthropic",
        previous_status="CRITICAL",
        new_status="HEALTHY",
    )
    assert handle_credential_event(event, fake_store) is False
    assert fake_store._client.get(rate_limit_key("anthropic", "cred-5")) is None
