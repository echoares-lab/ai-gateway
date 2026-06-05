"""Read-only credential_inventory access for rate-limit aggregation (38-7)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from schemas import RateLimitSnapshot

logger = logging.getLogger(__name__)

INVENTORY_COOLDOWN_SELECT = """
    SELECT credential_id, provider, cool_down_until
    FROM credential_inventory
    WHERE credential_id = ANY(%s)
      AND cool_down_until IS NOT NULL
      AND cool_down_until > now()
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


class InventoryStore:
    """Fail-open read layer for credential_inventory cooldown state."""

    def __init__(
        self,
        connect: Callable[[], DbConnection] | None,
        *,
        enabled: bool = True,
        fixtures: dict[str, tuple[str | None, datetime | None]] | None = None,
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

    def cooldown_snapshots(self, credential_ids: list[str]) -> list[RateLimitSnapshot]:
        """Return RateLimitSnapshot entries from inventory cool_down_until."""
        if not credential_ids:
            return []

        now = datetime.now(timezone.utc)
        rows: list[tuple[str, str | None, datetime | None]] = []

        for cred_id in credential_ids:
            fixture = self._fixtures.get(cred_id)
            if fixture is not None:
                provider, cooldown_until = fixture
                if cooldown_until and cooldown_until > now:
                    rows.append((cred_id, provider, cooldown_until))

        if self._enabled:
            missing = [c for c in credential_ids if c not in self._fixtures]
            if missing:
                try:
                    conn = self._connect()
                    try:
                        with conn.cursor() as cur:
                            cur.execute(INVENTORY_COOLDOWN_SELECT, (missing,))
                            for cred_id, provider, cooldown_until in cur.fetchall():
                                parsed = _parse_dt(cooldown_until)
                                if parsed and parsed > now:
                                    rows.append((cred_id, provider, parsed))
                    finally:
                        conn.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Inventory cooldown read failed: %s", exc)

        snapshots: list[RateLimitSnapshot] = []
        for cred_id, provider, cooldown_until in rows:
            snapshots.append(
                RateLimitSnapshot(
                    provider=provider,
                    credential_id=cred_id,
                    in_cooldown=True,
                    cooldown_until=cooldown_until,
                )
            )
        return snapshots
