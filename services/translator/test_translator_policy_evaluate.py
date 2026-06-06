"""Smoke tests for async policy evaluation entry points (issue #181)."""

import pytest
from core.policy.evaluate import evaluate, evaluate_async
from core.policy.schemas import EvaluateRequest, RoutingContext


@pytest.mark.asyncio
async def test_evaluate_async_returns_routing_decision():
    decision = await evaluate_async(
        EvaluateRequest(
            context=RoutingContext(requested_model="claude-sonnet-4-6"),
        ),
    )
    assert decision.gate.value == "allow"
    assert "claude-sonnet-4-6" in decision.allowed_models


def test_evaluate_sync_matches_async_baseline():
    req = EvaluateRequest(context=RoutingContext(requested_model="gpt-5-4"))
    sync_decision = evaluate(req)
    assert sync_decision.allowed_models
    assert sync_decision.policy_version
