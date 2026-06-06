"""Credential inventory event handler (Epic #38, issue 38-12)."""

from __future__ import annotations

from datetime import datetime

from core.policy.redis_store import RedisStateStore, _utcnow
from core.policy.schemas import CredentialEvent

COOLDOWN_STATUSES = frozenset({"DEGRADED", "COOLDOWN", "CRITICAL", "SUSPENDED", "EXPIRED"})
SUSPENDED_STATUSES = frozenset({"CRITICAL", "SUSPENDED", "EXPIRED"})
DEFAULT_SUSPENDED_COOLDOWN_SECONDS = 604800
RATE_LIMIT_STATUS = "RATE_LIMITED"
RATE_LIMIT_KEYWORDS = ("429", "rate limit", "rate_limit", "rate-limited")


def _event_timestamp(event: CredentialEvent) -> datetime:
    return event.timestamp or _utcnow()


def _is_rate_limited(event: CredentialEvent) -> bool:
    if event.new_status == RATE_LIMIT_STATUS:
        return True
    reason = (event.reason or "").lower()
    return any(keyword in reason for keyword in RATE_LIMIT_KEYWORDS)


def handle_credential_event(event: CredentialEvent, store: RedisStateStore) -> bool:
    """Apply credential transition to Redis cooldown registry (fail-open)."""
    if not event.provider:
        return False

    event_at = _event_timestamp(event)
    if _is_rate_limited(event):
        store.record_rate_limit_429(
            event.provider,
            event.credential_id,
            cooldown_until=event.cool_down_until,
            event_at=event_at,
        )
        return True

    if event.new_status in COOLDOWN_STATUSES:
        cooldown_seconds = (
            DEFAULT_SUSPENDED_COOLDOWN_SECONDS
            if event.new_status in SUSPENDED_STATUSES and event.cool_down_until is None
            else 60
        )
        store.apply_credential_cooldown(
            event.provider,
            event.credential_id,
            cooldown_until=event.cool_down_until,
            cooldown_seconds=cooldown_seconds,
            event_at=event_at,
            status=event.new_status,
        )
        return True

    return False
