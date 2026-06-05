"""Unit tests for credential event webhook (issue 38-12)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
from fastapi.testclient import TestClient

from evaluator.credential_events import handle_credential_event
from main import app, evaluate, get_redis_store
from redis_store import RedisStateStore, rate_limit_key
from schemas import CredentialEvent, EvaluateRequest, RateLimitSnapshot, RoutingContext


@pytest.fixture
def fake_store() -> RedisStateStore:
    client = fakeredis.FakeRedis(decode_responses=True)
    return RedisStateStore(client)


@pytest.fixture
def client(fake_store: RedisStateStore):
    get_redis_store.cache_clear()
    app.dependency_overrides[get_redis_store] = lambda: fake_store
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_redis_store.cache_clear()


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


def test_event_endpoint_returns_202(client: TestClient, fake_store: RedisStateStore):
    resp = client.post(
        "/v1/events/credential",
        json={
            "credential_id": "cred-4",
            "provider": "anthropic",
            "previous_status": "HEALTHY",
            "new_status": "CRITICAL",
            "reason": "401 Unauthorized",
        },
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": True}
    snap = fake_store.rate_limit_to_snapshot("anthropic", "cred-4")
    assert snap is not None
    assert snap.in_cooldown is True


def test_evaluate_reflects_event_cooldown(client: TestClient, fake_store: RedisStateStore):
    cooldown = datetime.now(timezone.utc) + timedelta(seconds=120)
    client.post(
        "/v1/events/credential",
        json={
            "credential_id": "cred-hot",
            "provider": "gemini",
            "previous_status": "HEALTHY",
            "new_status": "DEGRADED",
            "cool_down_until": cooldown.isoformat(),
        },
    )
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
    assert "cred-hot" in decision.deprioritized_credentials
    assert "rate_limit:cooldown_skip" in decision.rules_applied



def test_suspended_event_sets_long_cooldown(fake_store: RedisStateStore):
    event = CredentialEvent(
        credential_id="cred-susp", provider="openai", previous_status="HEALTHY",
        new_status="SUSPENDED", reason="operator disabled",
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
