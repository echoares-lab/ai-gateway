from dataclasses import dataclass


@dataclass
class _PolicyTraceState:
    evaluate_ms: float | None = None
    evaluated_at: str | None = None
    decision: dict | None = None
    error: str | None = None


_policy_trace = _PolicyTraceState()
