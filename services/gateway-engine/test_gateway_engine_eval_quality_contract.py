"""C-RT-2 contract fixtures; runtime enablement is intentionally out of scope."""

import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

from core.policy.quality import apply_quality_reorder, extract_eval_config

CONTRACT_VERSION = "eval-quality.v1"
LAYER_ORDER = (
    "capability",
    "allowlist",
    "affinity",
    "rate_limit",
    "health",
    "eval_quality",
    "cost_tier",
    "baseline",
)


def _record(*, score=0.8, samples=50, confidence=0.9, observed_at=None, window_days=7):
    return {
        "version": CONTRACT_VERSION,
        "task_category": "code_edit",
        "model": "gpt-5-4",
        "score": score,
        "sample_count": samples,
        "confidence": confidence,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "window_days": window_days,
    }


def _usable(record, *, now, min_samples=50, window_days=7):
    if record.get("version") != CONTRACT_VERSION:
        return False
    if not isinstance(record.get("score"), (int, float)) or not math.isfinite(record["score"]):
        return False
    if not 0 <= record["score"] <= 1:
        return False
    if not isinstance(record.get("confidence"), (int, float)) or not 0 <= record["confidence"] <= 1:
        return False
    if not isinstance(record.get("sample_count"), int) or record["sample_count"] < min_samples:
        return False
    try:
        observed = datetime.fromisoformat(str(record["observed_at"]).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    age = now - observed
    return age >= timedelta(0) and age <= timedelta(days=min(window_days, int(record.get("window_days", 0))))


def test_contract_version_and_layer_order_are_stable():
    assert CONTRACT_VERSION == "eval-quality.v1"
    assert LAYER_ORDER.index("health") < LAYER_ORDER.index("eval_quality") < LAYER_ORDER.index("cost_tier")


def test_default_off_preserves_existing_candidate_order(monkeypatch):
    monkeypatch.delenv("POLICY_EVAL_QUALITY_ENABLED", raising=False)
    config = extract_eval_config([])
    before = ["gpt-5-4", "gemini-3-flash", "claude-sonnet-4-6"]
    result = apply_quality_reorder(
        before,
        requested_model="gpt-5-4",
        eval_config=config,
        task_category="code_edit",
        health_scores={"gemini-3-flash": 0.2, "claude-sonnet-4-6": 0.9},
    )
    assert config.enabled is False
    assert result.candidates == before
    assert result.applied is False
    assert result.rules_applied == []


def test_invalid_stale_and_low_sample_records_fail_open():
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert _usable(_record(), now=now) is False  # current timestamp is after the fixture clock
    assert _usable(_record(observed_at="not-a-timestamp"), now=now) is False
    assert _usable(_record(samples=49, observed_at="2026-08-01T00:00:00Z"), now=now) is False
    assert _usable(_record(observed_at="2026-07-01T00:00:00Z"), now=now) is False


def test_valid_record_bounds_and_observability_allowlist():
    now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    assert _usable(_record(observed_at="2026-08-01T00:00:00Z"), now=now)
    assert not _usable(_record(score=1.1, observed_at="2026-08-01T00:00:00Z"), now=now)
    allowed_audit_fields = {
        "version",
        "task_category",
        "request_id_hash",
        "eligible_count",
        "scored_count",
        "applied",
        "age_bucket",
        "duration_ms",
        "outcome",
    }
    assert "prompt" not in allowed_audit_fields
    assert "credentials" not in allowed_audit_fields
