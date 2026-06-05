"""Read-only credential_inventory access for rate-limit aggregation (38-7, P0-6)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from schemas import RateLimitSnapshot

logger = logging.getLogger(__name__)

ROUTING_EXCLUDED_STATUSES = frozenset({"DEGRADED", "CRITICAL", "SUSPENDED", "EXPIRED"})

INVENTORY_ROUTING_SELECT = """
    SELECT credential_id, provider, status, cool_down_until
    FROM credential_inventory
    WHERE credential_id = ANY(%s)
"""


class DbConnection(Protocol):
    def cursor(self) -> Any: ...

    def close(self) -> None: ...


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _status_excludes_routing(status: str, cool_down_until: datetime | None, now: datetime) -> bool:
    if status in {"CRITICAL", "SUSPENDED", "EXPIRED"}:
        return True
    if status == "DEGRADED":
        if cool_down_until is None:
            return True
        return cool_down_until > now
    if cool_down_until is not None and cool_down_until > now:
        return True
    return False


def _snapshot_from_row(
    cred_id: str,
    provider: str | None,
    status: str,
    cool_down_until: datetime | None,
    *,
    now: datetime,
) -> RateLimitSnapshot | None:
    if not _status_excludes_routing(status, cool_down_until, now):
        return None
    in_cooldown = status in ROUTING_EXCLUDED_STATUSES or (
        cool_down_until is not None and cool_down_until > now
    )
    preemptive = status in {"CRITICAL", "SUSPENDED", "EXPIRED"}
    return RateLimitSnapshot(
        provider=provider,
        credential_id=cred_id,
        in_cooldown=in_cooldown,
        cooldown_until=cool_down_until,
        pre_emptive_degraded=preemptive,
    )


class InventoryStore:
    """Fail-open read layer for credential_inventory routing exclusion state."""

    def __init__(
        self,
        connect: Callable[[], DbConnection] | None,
        *,
        enabled: bool = True,
        fixtures: dict[str, tuple[str | None, datetime | None] | tuple[str | None, datetime | None, str | None]] | None = None,
    ) -> None:
        self._connect = connect
        self._enabled = enabled and connect is not None
        self._fixtures = fixtures or {}

    @classmethod
    def from_env(cls) -> InventoryStore:
        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            return cls(None, enabled=False)
        try:
            import psycopg2  # type: ignore[import-untyped]

            def _connect() -> DbConnection:
                return psycopg2.connect(url)

            conn = _connect()
            conn.close()
            return cls(_connect)
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("Postgres unavailable, credential inventory disabled: %s", exc)
            return cls(None, enabled=False)

    @property
    def enabled(self) -> bool:
        return self._enabled or bool(self._fixtures)

    def routing_snapshots(self, credential_ids: list[str]) -> list[RateLimitSnapshot]:
        if not credential_ids:
            return []

        now = datetime.now(timezone.utc)
        rows: list[tuple[str, str | None, str, datetime | None]] = []

        for cred_id in credential_ids:
            fixture = self._fixtures.get(cred_id)
            if fixture is not None:
                if len(fixture) == 2:
                    provider, cooldown_until = fixture
                    status = "HEALTHY"
                else:
                    provider, cooldown_until, status = fixture[0], fixture[1], fixture[2]
                    status = status or "HEALTHY"
                rows.append((cred_id, provider, status, cooldown_until))

        if self._enabled:
            missing = [c for c in credential_ids if c not in self._fixtures]
            if missing:
                try:
                    conn = self._connect()
                    try:
                        with conn.cursor() as cur:
                            cur.execute(INVENTORY_ROUTING_SELECT, (missing,))
                            for cred_id, provider, status, cooldown_until in cur.fetchall():
                                rows.append((cred_id, provider, status, _parse_dt(cooldown_until)))
                    finally:
                        conn.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Inventory routing read failed: %s", exc)

        snapshots: list[RateLimitSnapshot] = []
        for cred_id, provider, status, cooldown_until in rows:
            snap = _snapshot_from_row(cred_id, provider, status, cooldown_until, now=now)
            if snap is not None:
                snapshots.append(snap)
        return snapshots

    def cooldown_snapshots(self, credential_ids: list[str]) -> list[RateLimitSnapshot]:
        return self.routing_snapshots(credential_ids)
