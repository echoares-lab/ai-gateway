"""Validation-only contract for operator credential remediation actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class RemediationAction(StrEnum):
    DISABLE = "disable"
    ENABLE = "enable"
    RESET_COOLDOWN = "reset_cooldown"
    PROBE = "probe"


@dataclass(frozen=True)
class RemediationDecision:
    accepted: bool
    changed: bool
    target_status: str
    audit: dict[str, str]


_REDACT = re.compile(r"(?i)(token|secret|key|password)=\S+")


def _safe_reason(reason: str) -> str:
    return _REDACT.sub(r"\1=[redacted]", str(reason)).strip()[:160]


def validate_remediation(
    *, action: RemediationAction | str, current_status: str, actor: str, reason: str
) -> RemediationDecision:
    if not actor.strip():
        raise ValueError("actor is required")
    action_value = RemediationAction(action)
    status = current_status.upper()
    if not reason.strip():
        raise ValueError("reason is required")
    if action_value is RemediationAction.DISABLE:
        target = "SUSPENDED"
    elif action_value is RemediationAction.ENABLE:
        if status not in {"SUSPENDED", "EXPIRED", "HEALTHY"}:
            raise ValueError(f"action enable not allowed from {status}")
        target = "HEALTHY"
    elif action_value is RemediationAction.RESET_COOLDOWN:
        if status not in {"RATE_LIMITED", "DEGRADED"}:
            raise ValueError(f"action reset_cooldown not allowed from {status}")
        target = "HEALTHY"
    else:
        target = status
    return RemediationDecision(
        accepted=True,
        changed=target != status,
        target_status=target,
        audit={"action": action_value.value, "actor": actor.strip()[:120], "reason": _safe_reason(reason)},
    )
