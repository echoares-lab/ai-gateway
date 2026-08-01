"""Injectable policy boundary shared by protocol adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable


def redact_policy_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded, operator-safe subset of a routing decision."""
    sample: dict[str, Any] = {
        key: decision[key] for key in ("gate", "rules_applied", "policy_version") if key in decision
    }
    if decision.get("quota_aware_mode"):
        sample["quota_aware_mode"] = True
        credentials = decision.get("deprioritized_credentials")
        if credentials:
            sample["deprioritized_credentials"] = list(credentials)
    if decision.get("session_key"):
        sample["session_key"] = "[redacted]"
    return sample


@dataclass(frozen=True)
class PolicyHookBoundary:
    """Callbacks injected into HTTP and optional WebSocket protocol adapters."""

    enabled: Callable[[], bool]
    build_context: Callable[..., dict[str, Any]]
    evaluate: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]
    apply: Callable[[str | None, dict[str, Any]], Awaitable[dict[str, Any]]]
    record_trace: Callable[..., None]
    redact_decision: Callable[[dict[str, Any]], dict[str, Any]]
