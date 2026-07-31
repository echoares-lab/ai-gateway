"""Pure adaptive-routing contract primitives.

The runtime integration deliberately lives elsewhere.  This module defines the
bounded, fail-open decision contract used by both the signal collector and the
fallback evaluator: capability fit is a hard filter, while fresh passive
signals only influence ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import isfinite
from threading import Lock


@dataclass(frozen=True)
class DeploymentSignal:
    """Passive signal snapshot for one model deployment."""

    model: str
    health_factor: float = 1.0
    p95_latency_ms: float | None = None
    error_rate: float = 0.0
    rolling_429_count: int = 0
    cooldown_until: datetime | None = None
    observed_at: datetime | None = None
    supports_tools: bool = True
    supports_vision: bool = False
    context_window_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "health_factor", _bounded(self.health_factor))
        object.__setattr__(self, "error_rate", _bounded(self.error_rate))
        object.__setattr__(self, "p95_latency_ms", _nonnegative(self.p95_latency_ms))
        if self.rolling_429_count < 0:
            raise ValueError("rolling_429_count must be non-negative")

    def is_fresh(self, *, now: datetime, max_age: timedelta) -> bool:
        if self.observed_at is None:
            return False
        observed = _utc(self.observed_at)
        return observed <= _utc(now) and _utc(now) - observed <= max_age

    def in_cooldown(self, *, now: datetime) -> bool:
        return self.cooldown_until is not None and _utc(now) < _utc(self.cooldown_until)


@dataclass(frozen=True)
class RoutingNeeds:
    """Request-shape requirements used as a hard eligibility filter."""

    tools: bool = False
    vision: bool = False
    estimated_tokens: int | None = None


@dataclass(frozen=True)
class AdaptiveRoutingResult:
    ordered_models: list[str]
    eligible_models: list[str]
    skipped_models: list[str] = field(default_factory=list)
    used_adaptive_signals: bool = False


class AdaptiveSignalStore:
    """Small in-process passive signal registry."""

    def __init__(self) -> None:
        self._signals: dict[str, DeploymentSignal] = {}
        self._lock = Lock()

    def observe(
        self,
        model: str,
        *,
        status_code: int,
        latency_ms: float,
        now: datetime | None = None,
        cooldown: timedelta = timedelta(minutes=1),
        supports_tools: bool = True,
        supports_vision: bool = False,
        context_window_tokens: int | None = None,
    ) -> DeploymentSignal:
        """Record one passive outcome and return the updated signal."""
        now = now or datetime.now(timezone.utc)
        with self._lock:
            previous = self._signals.get(model)
            failures = status_code >= 500 or status_code == 429
            prior_errors = previous.error_rate if previous else 0.0
            prior_health = previous.health_factor if previous else 1.0
            error_rate = min(1.0, prior_errors * 0.8 + (1.0 if failures else 0.0) * 0.2)
            health = min(1.0, max(0.0, prior_health * 0.8 + (0.0 if failures else 1.0) * 0.2))
            count_429 = (previous.rolling_429_count if previous else 0) + (1 if status_code == 429 else 0)
            self._signals[model] = DeploymentSignal(
                model=model,
                health_factor=health,
                p95_latency_ms=max(0.0, latency_ms),
                error_rate=error_rate,
                rolling_429_count=count_429,
                cooldown_until=now + cooldown
                if status_code == 429
                else (previous.cooldown_until if previous else None),
                observed_at=now,
                supports_tools=supports_tools,
                supports_vision=supports_vision,
                context_window_tokens=context_window_tokens,
            )
            return self._signals[model]

    def snapshot(self) -> dict[str, DeploymentSignal]:
        with self._lock:
            return dict(self._signals)


def coerce_signals(value: object) -> dict[str, DeploymentSignal]:
    """Convert metadata snapshots into validated signal objects, fail-open."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, DeploymentSignal] = {}
    for model, raw in value.items():
        if isinstance(raw, DeploymentSignal):
            result[str(model)] = raw
            continue
        if not isinstance(raw, dict):
            continue
        try:
            result[str(model)] = DeploymentSignal(model=str(model), **raw)
        except (TypeError, ValueError):
            continue
    return result


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _bounded(value: float) -> float:
    if not isfinite(value):
        return 0.0
    return min(1.0, max(0.0, value))


def _nonnegative(value: float | None) -> float | None:
    if value is None or not isfinite(value):
        return None
    return max(0.0, value)


def capability_eligible(signal: DeploymentSignal, needs: RoutingNeeds) -> bool:
    """Return whether a deployment passes hard capability requirements."""
    if needs.tools and not signal.supports_tools:
        return False
    if needs.vision and not signal.supports_vision:
        return False
    return (
        needs.estimated_tokens is None
        or signal.context_window_tokens is None
        or signal.context_window_tokens >= needs.estimated_tokens
    )


def routing_score(signal: DeploymentSignal, *, latency_ceiling_ms: float = 30_000.0) -> float:
    """Compute a deterministic score in [0, 1]; higher is better.

    Missing latency is neutral.  429s and errors are penalized, but cooldown
    is handled as an ordering rule so a model can recover automatically.
    """
    latency = 0.0 if signal.p95_latency_ms is None else min(signal.p95_latency_ms / latency_ceiling_ms, 1.0)
    rate_limit_penalty = min(signal.rolling_429_count / 10.0, 1.0)
    return _bounded(0.55 * signal.health_factor - 0.15 * latency - 0.20 * signal.error_rate - 0.10 * rate_limit_penalty)


def order_adaptive(
    candidates: list[str],
    signals: dict[str, DeploymentSignal],
    *,
    needs: RoutingNeeds | None = None,
    now: datetime | None = None,
    max_signal_age: timedelta = timedelta(minutes=15),
    preserve_first: bool = False,
) -> AdaptiveRoutingResult:
    """Filter by capability, then order by fresh passive signal quality.

    If no candidate has a fresh signal, the original order is preserved.  This
    fail-open behavior keeps the static LiteLLM fallback list as the safety net.
    """
    now = now or datetime.now(timezone.utc)
    needs = needs or RoutingNeeds()
    unique = list(dict.fromkeys(candidates))
    eligible = [model for model in unique if model not in signals or capability_eligible(signals[model], needs)]
    skipped = [model for model in unique if model not in eligible]
    fresh = {
        model: signals[model]
        for model in eligible
        if model in signals and signals[model].is_fresh(now=now, max_age=max_signal_age)
    }
    if not fresh:
        return AdaptiveRoutingResult(eligible, eligible, skipped, False)
    position = {model: index for index, model in enumerate(eligible)}
    head = eligible[:1] if preserve_first else []
    tail = eligible[len(head) :]
    ordered = head + sorted(
        tail,
        key=lambda model: (
            model not in fresh,
            fresh[model].in_cooldown(now=now) if model in fresh else False,
            -routing_score(fresh[model]) if model in fresh else 0.0,
            position[model],
        ),
    )
    return AdaptiveRoutingResult(ordered, eligible, skipped, True)
