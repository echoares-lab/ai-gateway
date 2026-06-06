"""Reusable credential-prober normalization and payload helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_DEGRADED_COOLDOWN_SEC = 60
DEFAULT_CRITICAL_COOLDOWN_SEC = 604800

ROUTING_EXCLUDED = frozenset({"DEGRADED", "CRITICAL", "SUSPENDED", "EXPIRED"})

# CLIProxy auth-file provider names -> credential_inventory CHECK enum.
CLIPROXY_PROVIDER_MAP = {
    "antigravity": "gemini",
    "claude": "anthropic",
    "codex": "openai",
    "gemini-cli": "gemini",
}


def normalize_provider(cliproxy_provider: str | None) -> str:
    provider = (cliproxy_provider or "unknown").lower()
    return CLIPROXY_PROVIDER_MAP.get(provider, provider)


# CLIProxy sets status="error" for transient quota/rate limits as well as hard auth failures.
_RATE_LIMIT_MARKERS = ("429", "rate limit", "rate_limit", "rate-limited", "quota")
_HARD_AUTH_MARKERS = ("401", "unauthorized", "invalid key", "402", "403", "payment_required", "payment required")
_TRANSIENT_MARKERS = ("transient upstream error", "503", "504", "502", "500", "408")


def _status_message(file_data: dict[str, Any]) -> str:
    return (file_data.get("status_message") or "").lower()


def is_transient_cliproxy_error(file_data: dict[str, Any]) -> bool:
    """True when CLIProxy reports a recoverable quota or upstream error."""
    msg = _status_message(file_data)
    if any(marker in msg for marker in _RATE_LIMIT_MARKERS):
        return True
    if any(marker in msg for marker in _TRANSIENT_MARKERS):
        return True
    if file_data.get("unavailable") and not is_hard_cliproxy_auth_error(file_data):
        return True
    return False


def is_hard_cliproxy_auth_error(file_data: dict[str, Any]) -> bool:
    msg = _status_message(file_data)
    return any(marker in msg for marker in _HARD_AUTH_MARKERS)


def map_auth_file_status(file_data: dict[str, Any]) -> str:
    if file_data.get("disabled"):
        return "SUSPENDED"
    status = file_data.get("status")
    if status == "active":
        return "HEALTHY"
    if status == "error":
        if is_transient_cliproxy_error(file_data):
            return "DEGRADED"
        return "CRITICAL"
    return "DEGRADED"


def parse_next_retry_after(raw: Any, *, now: datetime) -> datetime | None:
    """Parse CLIProxy next_retry_after when present and still in the future."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        retry_at = raw
    else:
        try:
            retry_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    if retry_at <= now:
        return None
    return retry_at


def compute_cool_down_until(
    status: str,
    *,
    now: datetime | None = None,
    degraded_cooldown_sec: int = DEFAULT_DEGRADED_COOLDOWN_SEC,
    critical_cooldown_sec: int = DEFAULT_CRITICAL_COOLDOWN_SEC,
    next_retry_after: datetime | None = None,
) -> datetime | None:
    effective_now = now or datetime.now(timezone.utc)
    if next_retry_after is not None and next_retry_after > effective_now:
        return next_retry_after
    if status == "DEGRADED":
        return effective_now + timedelta(seconds=degraded_cooldown_sec)
    if status in ROUTING_EXCLUDED:
        return effective_now + timedelta(seconds=critical_cooldown_sec)
    return None


def build_inventory_payload(
    file_data: dict[str, Any],
    *,
    now: datetime | None = None,
    degraded_cooldown_sec: int = DEFAULT_DEGRADED_COOLDOWN_SEC,
    critical_cooldown_sec: int = DEFAULT_CRITICAL_COOLDOWN_SEC,
) -> dict[str, Any]:
    effective_now = now or datetime.now(timezone.utc)
    status = map_auth_file_status(file_data)
    retry_after = parse_next_retry_after(file_data.get("next_retry_after"), now=effective_now)
    return {
        "credential_id": file_data.get("id", "unknown"),
        "provider": normalize_provider(file_data.get("provider", "unknown")),
        "label": file_data.get("label") or file_data.get("account") or file_data.get("email") or "unknown",
        "key_fingerprint": file_data.get("auth_index") or "none",
        "status": status,
        "cool_down_until": compute_cool_down_until(
            status,
            now=effective_now,
            degraded_cooldown_sec=degraded_cooldown_sec,
            critical_cooldown_sec=critical_cooldown_sec,
            next_retry_after=retry_after,
        ),
        "consecutive_failures": file_data.get("failed", 0),
        "metadata": {
            "recent_requests": file_data.get("recent_requests", []),
            "status_message": file_data.get("status_message") or "",
            "updated_at": file_data.get("updated_at", ""),
        },
    }


def transition_reason(old_status: str | None, new_status: str, status_message: str | None) -> str:
    if status_message:
        msg_lower = status_message.lower()
        if new_status == "DEGRADED" and any(marker in msg_lower for marker in _RATE_LIMIT_MARKERS):
            if "429" not in msg_lower:
                return f"429 {status_message}"
        return status_message
    if old_status is None:
        return f"Initial import status: {new_status}"
    return f"Status changed from {old_status} to {new_status}"


def should_emit_transition(old_status: str | None, new_status: str) -> bool:
    if old_status is None:
        return new_status in ROUTING_EXCLUDED
    return old_status != new_status


def build_transition_payload(
    *,
    credential_id: str,
    provider: str,
    old_status: str | None,
    new_status: str,
    status_message: str | None,
    cool_down_until: datetime | None,
) -> dict[str, Any]:
    reason = transition_reason(old_status, new_status, status_message)
    return {
        "credential_id": credential_id,
        "provider": provider,
        "previous_status": old_status or "UNKNOWN",
        "new_status": new_status,
        "reason": reason,
        "cool_down_until": cool_down_until if new_status in ROUTING_EXCLUDED else None,
        "slack_event": f"credential_{new_status.lower()}",
    }


def build_policy_engine_event_payload(
    credential_id: str,
    provider: str,
    previous_status: str,
    new_status: str,
    *,
    reason: str | None = None,
    cool_down_until: datetime | None = None,
    timestamp: datetime | None = None,
) -> dict[str, str]:
    event_time = timestamp or datetime.now(timezone.utc)
    payload = {
        "credential_id": credential_id,
        "provider": provider,
        "previous_status": previous_status,
        "new_status": new_status,
        "timestamp": event_time.isoformat(),
    }
    if reason:
        payload["reason"] = reason
    if cool_down_until is not None:
        payload["cool_down_until"] = cool_down_until.isoformat()
    return payload
