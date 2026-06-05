"""Async routing decision audit log (Epic #38, issue 38-16)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import random
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from schemas import GateAction, RoutingContext, RoutingDecision

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = float(os.environ.get("POLICY_AUDIT_SAMPLE_RATE", "0.01"))
AUDIT_QUEUE_MAX = int(os.environ.get("POLICY_AUDIT_QUEUE_MAX", "1000"))

AUDIT_INSERT = """
    INSERT INTO routing_decisions_log (
        request_id, tenant_id, team_id, repo_name, agent_id,
        requested_model, gate, decision_json, policy_version, evaluated_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
"""


class DbConnection(Protocol):
    def cursor(self) -> Any: ...

    def commit(self) -> None: ...

    def close(self) -> None: ...


def compute_context_hash(context: RoutingContext) -> str:
    """Stable hash of routing inputs for dedup and incident correlation."""
    payload = context.model_dump(mode="json", exclude_none=True)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_decision_json(
    decision: RoutingDecision,
    *,
    context_hash: str,
) -> dict[str, Any]:
    """Serialize audit payload with quota-aware fields required by 38-16."""
    return {
        "context_hash": context_hash,
        "rules_applied": list(decision.rules_applied),
        "quota_aware_mode": decision.quota_aware_mode,
        "deprioritized_credentials": list(decision.deprioritized_credentials),
        "decision": decision.model_dump(mode="json"),
    }


def should_log_audit(
    gate: GateAction,
    *,
    sample_rate: float = DEFAULT_SAMPLE_RATE,
    rng: random.Random | None = None,
) -> bool:
    """Deny/throttle always logged; allow sampled at ``sample_rate``."""
    if gate in (GateAction.DENY, GateAction.THROTTLE):
        return True
    rate = max(0.0, min(1.0, sample_rate))
    if rate <= 0.0:
        return False
    if rate >= 1.0:
        return True
    roll = (rng or random).random()
    return roll < rate


def _extract_request_id(context: RoutingContext) -> str | None:
    raw = context.metadata.get("request_id")
    if raw is None:
        return None
    return str(raw)


class RoutingAuditWriter:
    """Fail-silent async writer for ``routing_decisions_log``."""

    def __init__(
        self,
        connect: Callable[[], DbConnection] | None,
        *,
        enabled: bool = True,
        sample_rate: float = DEFAULT_SAMPLE_RATE,
        sink: list[dict[str, Any]] | None = None,
    ) -> None:
        self._connect = connect
        self._enabled = enabled and (connect is not None or sink is not None)
        self._sample_rate = sample_rate
        self._sink = sink
        self._queue: queue.Queue[dict[str, Any] | None] | None = None
        self._worker: threading.Thread | None = None
        if self._enabled and sink is None and connect is not None:
            self._queue = queue.Queue(maxsize=AUDIT_QUEUE_MAX)
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="policy-audit-writer",
                daemon=True,
            )
            self._worker.start()

    @classmethod
    def from_env(cls) -> RoutingAuditWriter:
        url = os.environ.get("DATABASE_URL", "").strip()
        sample_rate = float(os.environ.get("POLICY_AUDIT_SAMPLE_RATE", "0.01"))
        if not url:
            return cls(None, enabled=False, sample_rate=sample_rate)
        try:
            import psycopg2  # type: ignore[import-untyped]

            def _connect() -> DbConnection:
                return psycopg2.connect(url)

            conn = _connect()
            conn.close()
            return cls(_connect, sample_rate=sample_rate)
        except Exception as exc:  # noqa: BLE001 — fail-silent
            logger.warning("Postgres unavailable, routing audit disabled: %s", exc)
            return cls(None, enabled=False, sample_rate=sample_rate)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def maybe_log(
        self,
        context: RoutingContext,
        decision: RoutingDecision,
        *,
        rng: random.Random | None = None,
    ) -> bool:
        """Enqueue an audit row when sampling selects this decision."""
        if not self._enabled or context.dry_run:
            return False
        if not should_log_audit(decision.gate, sample_rate=self._sample_rate, rng=rng):
            return False

        context_hash = compute_context_hash(context)
        record = {
            "request_id": _extract_request_id(context),
            "tenant_id": context.tenancy.tenant_id,
            "team_id": context.tenancy.team_id,
            "repo_name": context.tenancy.repo_name,
            "agent_id": context.agent_id,
            "requested_model": context.requested_model,
            "gate": decision.gate.value,
            "decision_json": build_decision_json(decision, context_hash=context_hash),
            "policy_version": decision.policy_version,
            "evaluated_at": decision.evaluated_at,
        }

        if self._sink is not None:
            self._sink.append(record)
            return True

        if self._queue is None:
            return False
        try:
            self._queue.put_nowait(record)
            return True
        except queue.Full:
            logger.warning("Policy audit queue full; dropping record")
            return False

    def flush(self, timeout: float = 2.0) -> None:
        """Drain async queue (tests / graceful shutdown)."""
        if self._queue is None:
            return
        sentinel: dict[str, Any] | None = None
        self._queue.put(sentinel)
        if self._worker is not None:
            self._worker.join(timeout=timeout)

    def _worker_loop(self) -> None:
        if self._queue is None or self._connect is None:
            return
        while True:
            record = self._queue.get()
            if record is None:
                break
            try:
                self._write_record(record)
            except Exception as exc:  # noqa: BLE001 — fail-silent
                logger.warning("Policy audit write failed: %s", exc)
            finally:
                self._queue.task_done()

    def _write_record(self, record: dict[str, Any]) -> None:
        if self._connect is None:
            return
        evaluated_at = record["evaluated_at"]
        if isinstance(evaluated_at, datetime) and evaluated_at.tzinfo is None:
            evaluated_at = evaluated_at.replace(tzinfo=timezone.utc)

        decision_json = json.dumps(record["decision_json"])
        params = (
            record["request_id"],
            record["tenant_id"],
            record["team_id"],
            record["repo_name"],
            record["agent_id"],
            record["requested_model"],
            record["gate"],
            decision_json,
            record["policy_version"],
            evaluated_at,
        )

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(AUDIT_INSERT, params)
            conn.commit()
        finally:
            conn.close()
