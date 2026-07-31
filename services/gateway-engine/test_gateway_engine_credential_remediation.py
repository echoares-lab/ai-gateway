"""Contract tests for operator credential remediation actions (#568)."""

import pytest
from core.credential_remediation import (
    RemediationAction,
    validate_remediation,
)


def test_disable_and_enable_are_authorized_and_auditable():
    result = validate_remediation(
        action=RemediationAction.DISABLE,
        current_status="CRITICAL",
        actor="operator@example.com",
        reason="rotate credential",
    )
    assert result.accepted is True
    assert result.target_status == "SUSPENDED"
    assert result.audit["actor"] == "operator@example.com"
    assert result.audit["reason"] == "rotate credential"


def test_recovery_action_is_idempotent():
    result = validate_remediation(
        action=RemediationAction.ENABLE,
        current_status="HEALTHY",
        actor="operator",
        reason="already enabled",
    )
    assert result.accepted is True
    assert result.changed is False
    assert result.target_status == "HEALTHY"


def test_invalid_action_and_missing_actor_are_rejected():
    with pytest.raises(ValueError, match="actor is required"):
        validate_remediation(action="probe", current_status="HEALTHY", actor="", reason="check")
    with pytest.raises(ValueError, match="not allowed"):
        validate_remediation(action="enable", current_status="CRITICAL", actor="operator", reason="manual")


def test_audit_reason_is_bounded_and_secret_free():
    result = validate_remediation(
        action="reset_cooldown",
        current_status="RATE_LIMITED",
        actor="operator",
        reason="token=sk-secret-value " + "x" * 500,
    )
    assert len(result.audit["reason"]) <= 160
    assert "sk-secret" not in result.audit["reason"]
