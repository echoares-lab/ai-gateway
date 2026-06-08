from collections import deque
from dataclasses import dataclass


@dataclass
class _PolicyTraceState:
    evaluate_ms: float | None = None
    evaluated_at: str | None = None
    decision: dict | None = None
    error: str | None = None


_policy_trace = _PolicyTraceState()
_policy_history: deque[dict] = deque(maxlen=50)


def record_policy_history(
    decision: dict | None,
    evaluate_ms: float,
    *,
    error: str | None = None,
) -> None:
    from datetime import datetime, timezone

    _policy_history.append(
        {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "evaluate_ms": round(evaluate_ms, 2),
            "decision": decision,
            "error": error,
        }
    )
