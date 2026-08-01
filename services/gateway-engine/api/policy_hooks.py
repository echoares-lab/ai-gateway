"""Injectable policy boundary shared by protocol adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi.responses import JSONResponse


class PolicyDeniedError(Exception):
    """Raised when opt-in strict HTTP enforcement returns a deny decision."""

    def __init__(self, decision: dict[str, Any]):
        super().__init__("policy denied")
        self.decision = decision


def policy_denial_response(protocol: str = "openai") -> JSONResponse:
    """Build a stable, protocol-shaped denial without exposing policy details."""
    message = "Request denied by policy."
    if protocol == "claude":
        content = {"type": "error", "error": {"type": "permission_error", "message": message}}
    elif protocol == "gemini":
        content = {"error": {"code": 403, "message": message, "status": "PERMISSION_DENIED"}}
    else:
        content = {"error": {"type": "policy_denied", "code": "policy_denied", "message": message}}
    return JSONResponse(status_code=403, content=content)


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
