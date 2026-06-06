"""Unit tests for in-process policy evaluator (Epic 2, issue #181)."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from core.policy.evaluate import evaluate
from core.policy.schemas import (
    EvaluateRequest,
    QuotaHeadroom,
    RateLimitSnapshot,
    RoutingContext,
)


def test_evaluate_pass_through_stub():
    decision = evaluate(
        EvaluateRequest(context=RoutingContext(requested_model="claude-sonnet-4-6"))
    )
    assert decision.gate.value == "allow"
    assert decision.allowed_models == ["claude-sonnet-4-6"]
    assert "stub:pass_through" in decision.rules_applied


def test_evaluate_preemptive_deprioritize_on_high_429_count():
    ctx = RoutingContext(
        requested_model="gemini-3-flash",
        rate_limits=[
            RateLimitSnapshot(
                provider="gemini",
                credential_id="cred-a",
                rolling_429_count_5m=5,
            )
        ],
    )
    decision = evaluate(EvaluateRequest(context=ctx))
    assert "cred-a" in decision.deprioritized_credentials
    assert "rate_limit:preemptive_deprioritize" in decision.rules_applied
    assert decision.quota_aware_mode is True


def test_evaluate_quota_aware_mode_from_pool_affinity():
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        pool_affinity_mode="quota-aware",
    )
    decision = evaluate(EvaluateRequest(context=ctx))
    assert decision.quota_aware_mode is True
    assert "pool:quota_aware_mode" in decision.rules_applied


def test_evaluate_soft_deprioritize_low_headroom():
    ctx = RoutingContext(
        requested_model="gpt-5-4",
        quota_headroom=[
            QuotaHeadroom(
                credential_id="cred-low",
                provider="openai",
                headroom_pct=5.0,
                below_soft_threshold=True,
            )
        ],
    )
    decision = evaluate(EvaluateRequest(context=ctx))
    assert "cred-low" in decision.deprioritized_credentials
    assert "budget:soft_deprioritize" in decision.rules_applied
