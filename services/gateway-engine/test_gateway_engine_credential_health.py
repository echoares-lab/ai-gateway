"""Contract tests for credential pool health transitions (C-CRED-1/#556)."""

from datetime import datetime, timedelta, timezone

import pytest
from core.credential_health import (
    CredentialHealthEvent,
    CredentialHealthStatus,
    transition_credential_health,
)

NOW = datetime(2026, 7, 31, 21, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("current", "event", "expected"),
    [
        (CredentialHealthStatus.HEALTHY, CredentialHealthEvent.TRANSIENT_FAILURE, CredentialHealthStatus.DEGRADED),
        (CredentialHealthStatus.DEGRADED, CredentialHealthEvent.RATE_LIMITED, CredentialHealthStatus.RATE_LIMITED),
        (CredentialHealthStatus.RATE_LIMITED, CredentialHealthEvent.COOLDOWN_EXPIRED, CredentialHealthStatus.HEALTHY),
        (CredentialHealthStatus.CRITICAL, CredentialHealthEvent.RECOVERED, CredentialHealthStatus.HEALTHY),
    ],
)
def test_legal_transitions_are_deterministic(current, event, expected):
    result = transition_credential_health(current, event, now=NOW)
    assert result.status is expected
    assert result.changed is True


def test_cooldown_blocks_recovery_until_expiry():
    result = transition_credential_health(
        CredentialHealthStatus.RATE_LIMITED,
        CredentialHealthEvent.RECOVERED,
        now=NOW,
        cooldown_until=NOW + timedelta(seconds=30),
    )
    assert result.status is CredentialHealthStatus.RATE_LIMITED
    assert result.changed is False
    assert result.reason == "cooldown_active"


def test_disabled_credentials_cannot_be_resurrected_by_success():
    result = transition_credential_health(
        CredentialHealthStatus.SUSPENDED,
        CredentialHealthEvent.RECOVERED,
        now=NOW,
        enabled=False,
    )
    assert result.status is CredentialHealthStatus.SUSPENDED
    assert result.changed is False
    assert result.reason == "credential_disabled"


def test_alert_is_redacted_and_stable():
    result = transition_credential_health(
        CredentialHealthStatus.HEALTHY,
        CredentialHealthEvent.AUTH_FAILURE,
        now=NOW,
        credential_id="cred-prod-7",
        provider="anthropic",
        reason="token=sk-secret-value rejected for account@example.com",
    )
    assert result.status is CredentialHealthStatus.CRITICAL
    assert result.alert == {
        "type": "credential_health_transition",
        "credential_id": "cred-prod-7",
        "provider": "anthropic",
        "from": "HEALTHY",
        "to": "CRITICAL",
        "reason": "auth_failure",
        "occurred_at": NOW.isoformat(),
    }
    assert "sk-secret" not in str(result.alert)
    assert "account@example.com" not in str(result.alert)


def test_unknown_transition_is_rejected():
    with pytest.raises(ValueError, match="illegal credential health transition"):
        transition_credential_health(
            CredentialHealthStatus.EXPIRED,
            CredentialHealthEvent.TRANSIENT_FAILURE,
            now=NOW,
        )
