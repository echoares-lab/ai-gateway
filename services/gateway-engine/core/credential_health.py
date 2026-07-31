"""Deterministic credential-pool health state machine."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class CredentialHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    CRITICAL = "CRITICAL"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class CredentialHealthEvent(StrEnum):
    TRANSIENT_FAILURE = "transient_failure"
    RATE_LIMITED = "rate_limited"
    AUTH_FAILURE = "auth_failure"
    RECOVERED = "recovered"
    COOLDOWN_EXPIRED = "cooldown_expired"
    DISABLE = "disable"
    ENABLE = "enable"


class CredentialHealthTransition:
    def __init__(
        self, *, status: CredentialHealthStatus, changed: bool, reason: str, alert: dict[str, Any] | None = None
    ) -> None:
        self.status = status
        self.changed = changed
        self.reason = reason
        self.alert = alert


_LEGAL: dict[tuple[CredentialHealthStatus, CredentialHealthEvent], CredentialHealthStatus] = {
    (CredentialHealthStatus.HEALTHY, CredentialHealthEvent.TRANSIENT_FAILURE): CredentialHealthStatus.DEGRADED,
    (CredentialHealthStatus.DEGRADED, CredentialHealthEvent.TRANSIENT_FAILURE): CredentialHealthStatus.DEGRADED,
    (CredentialHealthStatus.DEGRADED, CredentialHealthEvent.RATE_LIMITED): CredentialHealthStatus.RATE_LIMITED,
    (CredentialHealthStatus.HEALTHY, CredentialHealthEvent.RATE_LIMITED): CredentialHealthStatus.RATE_LIMITED,
    (CredentialHealthStatus.HEALTHY, CredentialHealthEvent.AUTH_FAILURE): CredentialHealthStatus.CRITICAL,
    (CredentialHealthStatus.DEGRADED, CredentialHealthEvent.AUTH_FAILURE): CredentialHealthStatus.CRITICAL,
    (CredentialHealthStatus.RATE_LIMITED, CredentialHealthEvent.AUTH_FAILURE): CredentialHealthStatus.CRITICAL,
    (CredentialHealthStatus.CRITICAL, CredentialHealthEvent.RECOVERED): CredentialHealthStatus.HEALTHY,
    (CredentialHealthStatus.DEGRADED, CredentialHealthEvent.RECOVERED): CredentialHealthStatus.HEALTHY,
    (CredentialHealthStatus.RATE_LIMITED, CredentialHealthEvent.RECOVERED): CredentialHealthStatus.HEALTHY,
    (CredentialHealthStatus.DEGRADED, CredentialHealthEvent.COOLDOWN_EXPIRED): CredentialHealthStatus.HEALTHY,
    (CredentialHealthStatus.RATE_LIMITED, CredentialHealthEvent.COOLDOWN_EXPIRED): CredentialHealthStatus.HEALTHY,
    (CredentialHealthStatus.HEALTHY, CredentialHealthEvent.DISABLE): CredentialHealthStatus.SUSPENDED,
    (CredentialHealthStatus.DEGRADED, CredentialHealthEvent.DISABLE): CredentialHealthStatus.SUSPENDED,
    (CredentialHealthStatus.RATE_LIMITED, CredentialHealthEvent.DISABLE): CredentialHealthStatus.SUSPENDED,
    (CredentialHealthStatus.CRITICAL, CredentialHealthEvent.DISABLE): CredentialHealthStatus.SUSPENDED,
    (CredentialHealthStatus.EXPIRED, CredentialHealthEvent.ENABLE): CredentialHealthStatus.HEALTHY,
    (CredentialHealthStatus.SUSPENDED, CredentialHealthEvent.ENABLE): CredentialHealthStatus.HEALTHY,
}


def transition_credential_health(
    current: CredentialHealthStatus | str,
    event: CredentialHealthEvent | str,
    *,
    now: datetime | None = None,
    cooldown_until: datetime | None = None,
    enabled: bool = True,
    credential_id: str = "unknown",
    provider: str = "unknown",
    reason: str | None = None,
) -> CredentialHealthTransition:
    """Evaluate one transition and return a sanitized, stable alert payload."""
    current_status = CredentialHealthStatus(current)
    health_event = CredentialHealthEvent(event)
    effective_now = now or datetime.now(timezone.utc)
    target = _LEGAL.get((current_status, health_event))
    if target is None:
        if (
            health_event in {CredentialHealthEvent.RECOVERED, CredentialHealthEvent.COOLDOWN_EXPIRED}
            and cooldown_until
            and effective_now < cooldown_until
        ):
            return CredentialHealthTransition(status=current_status, changed=False, reason="cooldown_active")
        if not enabled and health_event in {
            CredentialHealthEvent.RECOVERED,
            CredentialHealthEvent.COOLDOWN_EXPIRED,
            CredentialHealthEvent.ENABLE,
        }:
            return CredentialHealthTransition(status=current_status, changed=False, reason="credential_disabled")
        raise ValueError(f"illegal credential health transition: {current_status.value} + {health_event.value}")
    if (
        cooldown_until
        and effective_now < cooldown_until
        and health_event in {CredentialHealthEvent.RECOVERED, CredentialHealthEvent.COOLDOWN_EXPIRED}
    ):
        return CredentialHealthTransition(status=current_status, changed=False, reason="cooldown_active")
    if not enabled and health_event in {CredentialHealthEvent.RECOVERED, CredentialHealthEvent.COOLDOWN_EXPIRED}:
        return CredentialHealthTransition(status=current_status, changed=False, reason="credential_disabled")
    alert = {
        "type": "credential_health_transition",
        "credential_id": credential_id,
        "provider": provider,
        "from": current_status.value,
        "to": target.value,
        "reason": health_event.value,
        "occurred_at": effective_now.isoformat(),
    }
    return CredentialHealthTransition(
        status=target, changed=target != current_status, reason=reason or health_event.value, alert=alert
    )
