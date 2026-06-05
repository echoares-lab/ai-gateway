"""Unit tests for routing decision audit log (issue 38-16)."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from unittest.mock import MagicMock

from audit import (
    RoutingAuditWriter,
    build_decision_json,
    compute_context_hash,
    should_log_audit,
)
from schemas import GateAction, RoutingContext, RoutingDecision, TenancyContext


def _decision(
    *,
    gate: GateAction = GateAction.ALLOW,
    quota_aware_mode: bool = False,
    deprioritized_credentials: list[str] | None = None,
) -> RoutingDecision:
    return RoutingDecision(
        gate=gate,
        allowed_models=["claude-sonnet-4-6"],
        quota_aware_mode=quota_aware_mode,
        deprioritized_credentials=deprioritized_credentials or [],
        rules_applied=["stub:pass_through"],
        policy_version="v0-test",
        evaluated_at=datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc),
    )


def test_compute_context_hash_stable():
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        tenancy=TenancyContext(repo_name="gateway"),
        agent_id="agent-1",
    )
    assert compute_context_hash(ctx) == compute_context_hash(ctx)


def test_build_decision_json_includes_quota_fields():
    decision = _decision(
        quota_aware_mode=True,
        deprioritized_credentials=["cred-a", "cred-b"],
    )
    ctx_hash = "abc123"
    payload = build_decision_json(decision, context_hash=ctx_hash)
    assert payload["context_hash"] == ctx_hash
    assert payload["quota_aware_mode"] is True
    assert payload["deprioritized_credentials"] == ["cred-a", "cred-b"]
    assert "stub:pass_through" in payload["rules_applied"]
    assert payload["decision"]["gate"] == "allow"


def test_should_log_audit_always_deny_throttle():
    rng = random.Random(0)
    assert should_log_audit(GateAction.DENY, sample_rate=0.0, rng=rng) is True
    assert should_log_audit(GateAction.THROTTLE, sample_rate=0.0, rng=rng) is True


def test_should_log_audit_samples_allow():
    rng = random.Random(42)
    assert should_log_audit(GateAction.ALLOW, sample_rate=0.0, rng=rng) is False
    assert should_log_audit(GateAction.ALLOW, sample_rate=1.0, rng=rng) is True

    rng2 = random.Random(1)
    hits = sum(1 for _ in range(1000) if should_log_audit(GateAction.ALLOW, sample_rate=0.1, rng=rng2))
    assert 50 < hits < 150


def test_maybe_log_skips_dry_run():
    sink: list = []
    writer = RoutingAuditWriter(None, enabled=True, sample_rate=1.0, sink=sink)
    ctx = RoutingContext(requested_model="claude-sonnet-4-6", dry_run=True)
    logged = writer.maybe_log(ctx, _decision())
    assert logged is False
    assert sink == []


def test_maybe_log_always_records_deny():
    sink: list = []
    writer = RoutingAuditWriter(None, enabled=True, sample_rate=0.0, sink=sink)
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        tenancy=TenancyContext(tenant_id="t1", team_id="eng", repo_name="gateway"),
        agent_id="agent-9",
        metadata={"request_id": "req-42"},
    )
    decision = _decision(gate=GateAction.DENY)
    assert writer.maybe_log(ctx, decision, rng=random.Random(0)) is True
    assert len(sink) == 1
    row = sink[0]
    assert row["gate"] == "deny"
    assert row["request_id"] == "req-42"
    assert row["tenant_id"] == "t1"
    assert row["team_id"] == "eng"
    assert row["repo_name"] == "gateway"
    assert row["agent_id"] == "agent-9"
    assert row["decision_json"]["quota_aware_mode"] is False


def test_write_record_executes_insert():
    cursor = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    writer = RoutingAuditWriter(lambda: conn, enabled=True, sample_rate=1.0)
    writer._write_record(
        {
            "request_id": "req-1",
            "tenant_id": "t1",
            "team_id": None,
            "repo_name": "gateway",
            "agent_id": None,
            "requested_model": "claude-sonnet-4-6",
            "gate": "allow",
            "decision_json": build_decision_json(_decision(), context_hash="hash-1"),
            "policy_version": "v0-test",
            "evaluated_at": datetime(2026, 6, 5, 12, 0, 0, tzinfo=timezone.utc),
        }
    )
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()
    conn.close.assert_called_once()
