"""Unit tests for policy-engine schemas (issue 38-1)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from schemas import (
    EvaluateRequest,
    GateAction,
    QuotaHeadroom,
    RateLimitSnapshot,
    RequestCapabilities,
    RoutingContext,
    RoutingDecision,
    TenancyContext,
)


def test_routing_context_strips_ai_gateway_prefix():
    ctx = RoutingContext(requested_model="AI-Gateway:claude-sonnet-4-6")
    assert ctx.requested_model == "claude-sonnet-4-6"


def test_routing_decision_to_metadata_round_trip():
    decision = RoutingDecision(
        gate=GateAction.ALLOW,
        allowed_models=["gemini-3-flash"],
        fallback_chain=["gemini-3-flash", "claude-sonnet-4-6"],
        session_key="agent-abc",
        rules_applied=["repo_affinity:team-eng"],
    )
    meta = decision.to_metadata()
    assert meta["gate"] == "allow"
    assert meta["allowed_models"] == ["gemini-3-flash"]
    assert meta["session_key"] == "agent-abc"
    assert "debug" not in meta


def test_tenancy_context_optional_fields():
    tenancy = TenancyContext(
        tenant_id="echoares",
        workspace_id="core",
        team_id="eng",
        repo_name="gateway",
        environment="dev",
        api_key_label="ak-echoares-core-eng-gateway-dev",
    )
    ctx = RoutingContext(requested_model="gpt-5-4", tenancy=tenancy)
    assert ctx.tenancy.repo_name == "gateway"


def test_capabilities_tool_chain_flag():
    caps = RequestCapabilities(has_tools=True, active_tool_chain=True, model_family="anthropic")
    ctx = RoutingContext(requested_model="claude-sonnet-4-6", capabilities=caps)
    assert ctx.capabilities.active_tool_chain is True


def test_budget_pct_bounds():
    with pytest.raises(ValidationError):
        RoutingContext(
            requested_model="gpt-5-4",
            budget={"team_budget_pct_used": 150},
        )


def test_evaluate_request_nested_context():
    req = EvaluateRequest(
        context=RoutingContext(
            requested_model="gemini-3-flash",
            dry_run=True,
        )
    )
    assert req.context.dry_run is True


def test_routing_decision_evaluated_at_utc():
    decision = RoutingDecision()
    assert decision.evaluated_at.tzinfo is not None
    assert decision.evaluated_at.tzinfo == timezone.utc


def test_quota_headroom_and_quota_aware_decision_fields():
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        pool_affinity_mode="quota-aware",
        quota_headroom=[
            QuotaHeadroom(credential_id="cred-1", headroom_pct=42.0),
        ],
        rate_limits=[
            RateLimitSnapshot(credential_id="cred-1", rolling_429_count_5m=1),
        ],
    )
    assert ctx.pool_affinity_mode == "quota-aware"
    decision = RoutingDecision(
        quota_aware_mode=True,
        deprioritized_credentials=["cred-2"],
    )
    meta = decision.to_metadata()
    assert meta["quota_aware_mode"] is True
    assert meta["deprioritized_credentials"] == ["cred-2"]
