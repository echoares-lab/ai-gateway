from datetime import datetime, timedelta, timezone

from core.adaptive_routing import (
    DeploymentSignal,
    RoutingNeeds,
    capability_eligible,
    order_adaptive,
    routing_score,
)

NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)


def signal(model: str, **kwargs) -> DeploymentSignal:
    kwargs.setdefault("observed_at", NOW)
    return DeploymentSignal(model=model, **kwargs)


def test_capability_requirements_are_hard_filters():
    assert not capability_eligible(signal("text", supports_vision=False), RoutingNeeds(vision=True))
    assert not capability_eligible(signal("short", context_window_tokens=100), RoutingNeeds(estimated_tokens=101))
    assert capability_eligible(signal("vision", supports_vision=True), RoutingNeeds(vision=True))


def test_ordering_prefers_healthy_fast_deployment():
    result = order_adaptive(
        ["slow", "healthy"],
        {
            "slow": signal("slow", health_factor=0.4, p95_latency_ms=20_000, error_rate=0.2),
            "healthy": signal("healthy", health_factor=1.0, p95_latency_ms=100),
        },
        now=NOW,
    )
    assert result.ordered_models == ["healthy", "slow"]
    assert result.used_adaptive_signals


def test_cooldown_is_deprioritized_but_not_removed():
    result = order_adaptive(
        ["limited", "healthy"],
        {
            "limited": signal("limited", cooldown_until=NOW + timedelta(minutes=2)),
            "healthy": signal("healthy"),
        },
        now=NOW,
    )
    assert result.ordered_models == ["healthy", "limited"]
    assert result.eligible_models == ["limited", "healthy"]


def test_stale_or_missing_signals_preserve_static_order():
    result = order_adaptive(
        ["first", "second"],
        {"first": signal("first", observed_at=NOW - timedelta(hours=1))},
        now=NOW,
    )
    assert result.ordered_models == ["first", "second"]
    assert not result.used_adaptive_signals


def test_capability_filter_happens_before_scoring():
    result = order_adaptive(
        ["text", "vision"],
        {
            "text": signal("text", health_factor=1.0),
            "vision": signal("vision", supports_vision=True, health_factor=0.1),
        },
        needs=RoutingNeeds(vision=True),
        now=NOW,
    )
    assert result.ordered_models == ["vision"]
    assert result.skipped_models == ["text"]


def test_score_is_bounded_for_untrusted_values():
    score = routing_score(signal("x", health_factor=4, error_rate=-2, p95_latency_ms=10**9))
    assert 0 <= score <= 1
