"""Safety contract for model discovery probe outcomes."""

from __future__ import annotations

from enum import StrEnum


class DiscoveryDisposition(StrEnum):
    APPLY = "apply"
    PRESERVE = "preserve"
    REMOVE = "remove"


_HEALTHY = frozenset({"healthy", "ok", "available"})
_PRESERVE = frozenset(
    {
        "timeout",
        "transient",
        "temporarily_unavailable",
        "rate_limited",
        "auth_failure",
        "error",
        "malformed_response",
        "preserve",
    }
)
_MISSING = frozenset({"missing", "missing_model", "not_found"})


def classify_discovery_result(status: str, *, currently_advertised: bool) -> DiscoveryDisposition:
    """Classify a probe without allowing transient failures to delete models."""
    normalized = str(status or "").strip().lower()
    if normalized in _HEALTHY:
        return DiscoveryDisposition.APPLY
    if normalized in _MISSING:
        return DiscoveryDisposition.REMOVE if currently_advertised else DiscoveryDisposition.PRESERVE
    if normalized in _PRESERVE:
        return DiscoveryDisposition.PRESERVE
    raise ValueError(f"unknown discovery probe status: {normalized or 'empty'}")
