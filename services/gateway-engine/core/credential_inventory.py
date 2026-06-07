"""Gateway-engine-owned credential inventory helpers."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field

try:  # pragma: no cover - exercised only when psycopg2 is installed/configured
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
except Exception:  # pragma: no cover - local unit env may not have psycopg2
    psycopg2 = None
    Json = None
    RealDictCursor = None


DEFAULT_DEGRADED_COOLDOWN_SEC = 60
DEFAULT_CRITICAL_COOLDOWN_SEC = 604800
ROUTING_EXCLUDED = frozenset({"DEGRADED", "CRITICAL", "SUSPENDED", "EXPIRED"})
CLIPROXY_PROVIDER_MAP = {
    "antigravity": "gemini",
    "claude": "anthropic",
    "codex": "openai",
    "gemini-cli": "gemini",
}


class CredentialInventoryRecord(BaseModel):
    credential_id: str
    provider: str
    label: str
    key_fingerprint: str
    status: str = "HEALTHY"
    cool_down_until: datetime | None = None
    consecutive_failures: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CredentialInventoryListResponse(BaseModel):
    source: str = "postgres:credential_inventory"
    registry_available: bool
    credentials: list[CredentialInventoryRecord] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class CredentialInventorySyncRequest(BaseModel):
    dry_run: bool = True


class CredentialTransition(BaseModel):
    credential_id: str
    provider: str
    previous_status: str = "UNKNOWN"
    new_status: str
    reason: str
    cool_down_until: datetime | None = None


class CredentialInventorySyncResponse(BaseModel):
    accepted: bool = True
    dry_run: bool
    source: str = "cliproxy:/v0/management/auth-files"
    registry_available: bool
    discovered_count: int = 0
    imported_count: int = 0
    credentials: list[CredentialInventoryRecord] = Field(default_factory=list)
    transitions: list[CredentialTransition] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class CredentialProbeResponse(BaseModel):
    accepted: bool = False
    supported: bool = False
    credential_id: str
    status: str = "unsupported"
    errors: list[dict[str, Any]] = Field(default_factory=list)


def _database_url() -> str:
    return os.environ.get("CREDENTIAL_INVENTORY_DATABASE_URL") or os.environ.get("DATABASE_URL", "")


def normalize_provider(cliproxy_provider: str | None) -> str:
    provider = (cliproxy_provider or "unknown").lower()
    return CLIPROXY_PROVIDER_MAP.get(provider, provider)


def map_auth_file_status(file_data: dict[str, Any]) -> str:
    if file_data.get("disabled"):
        return "SUSPENDED"
    status = file_data.get("status")
    if status == "active":
        return "HEALTHY"
    if status == "error":
        return "CRITICAL"
    return "DEGRADED"


def compute_cool_down_until(
    status: str,
    *,
    now: datetime | None = None,
    degraded_cooldown_sec: int = DEFAULT_DEGRADED_COOLDOWN_SEC,
    critical_cooldown_sec: int = DEFAULT_CRITICAL_COOLDOWN_SEC,
) -> datetime | None:
    effective_now = now or datetime.now(timezone.utc)
    if status == "DEGRADED":
        return effective_now + timedelta(seconds=degraded_cooldown_sec)
    if status in ROUTING_EXCLUDED:
        return effective_now + timedelta(seconds=critical_cooldown_sec)
    return None


def record_from_auth_file(
    file_data: dict[str, Any],
    *,
    now: datetime | None = None,
    degraded_cooldown_sec: int = DEFAULT_DEGRADED_COOLDOWN_SEC,
    critical_cooldown_sec: int = DEFAULT_CRITICAL_COOLDOWN_SEC,
) -> CredentialInventoryRecord:
    status = map_auth_file_status(file_data)
    return CredentialInventoryRecord(
        credential_id=str(file_data.get("id") or file_data.get("name") or "unknown"),
        provider=normalize_provider(file_data.get("provider", "unknown")),
        label=str(file_data.get("label") or file_data.get("account") or file_data.get("email") or "unknown"),
        key_fingerprint=str(file_data.get("auth_index") or file_data.get("fingerprint") or "none"),
        status=status,
        cool_down_until=compute_cool_down_until(
            status,
            now=now,
            degraded_cooldown_sec=degraded_cooldown_sec,
            critical_cooldown_sec=critical_cooldown_sec,
        ),
        consecutive_failures=int(file_data.get("failed") or 0),
        metadata={
            "recent_requests": file_data.get("recent_requests", []),
            "status_message": file_data.get("status_message") or "",
            "updated_at": file_data.get("updated_at", ""),
        },
    )


def should_emit_transition(old_status: str | None, new_status: str) -> bool:
    if old_status is None:
        return new_status in ROUTING_EXCLUDED
    return old_status != new_status


def transition_for_record(
    record: CredentialInventoryRecord,
    old_status: str | None,
) -> CredentialTransition | None:
    if not should_emit_transition(old_status, record.status):
        return None
    status_message = record.metadata.get("status_message") if isinstance(record.metadata, dict) else None
    reason = (
        str(status_message)
        if status_message
        else (
            f"Initial import status: {record.status}"
            if old_status is None
            else f"Status changed from {old_status} to {record.status}"
        )
    )
    return CredentialTransition(
        credential_id=record.credential_id,
        provider=record.provider,
        previous_status=old_status or "UNKNOWN",
        new_status=record.status,
        reason=reason,
        cool_down_until=record.cool_down_until if record.status in ROUTING_EXCLUDED else None,
    )


def _error(code: str, message: str, source: str) -> dict[str, Any]:
    return {"code": code, "message": message, "source": source}


class CredentialInventoryStore:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url if database_url is not None else _database_url()

    @property
    def enabled(self) -> bool:
        return bool(self.database_url and psycopg2 is not None)

    def _connect(self):
        if not self.enabled:
            raise RuntimeError("credential inventory database is not configured")
        return psycopg2.connect(self.database_url)

    def list_credentials(self) -> CredentialInventoryListResponse:
        if not self.enabled:
            return CredentialInventoryListResponse(
                registry_available=False,
                errors=[
                    _error(
                        "registry_unavailable",
                        "DATABASE_URL or psycopg2 unavailable",
                        "postgres:credential_inventory",
                    )
                ],
            )
        try:
            with (
                self._connect() as conn,
                conn.cursor(cursor_factory=RealDictCursor) as cur,
            ):
                cur.execute(
                    """
                    SELECT credential_id, provider, label, key_fingerprint, status,
                           cool_down_until, consecutive_failures, metadata,
                           created_at, updated_at
                    FROM credential_inventory
                    ORDER BY provider, credential_id
                    """
                )
                rows = cur.fetchall()
        except Exception as exc:
            return CredentialInventoryListResponse(
                registry_available=False,
                errors=[
                    _error(
                        "registry_read_error",
                        f"{type(exc).__name__}: {exc}",
                        "postgres:credential_inventory",
                    )
                ],
            )
        return CredentialInventoryListResponse(
            registry_available=True,
            credentials=[CredentialInventoryRecord.model_validate(dict(row)) for row in rows],
        )

    def existing_statuses(self) -> dict[str, str]:
        if not self.enabled:
            raise RuntimeError("credential inventory database is not configured")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT credential_id, status FROM credential_inventory")
            return {str(row[0]): str(row[1]) for row in cur.fetchall()}

    def upsert_credentials(self, credentials: list[CredentialInventoryRecord]) -> int:
        if not self.enabled:
            raise RuntimeError("credential inventory database is not configured")
        if not credentials:
            return 0
        with self._connect() as conn, conn.cursor() as cur:
            for cred in credentials:
                cur.execute(
                    """
                    INSERT INTO credential_inventory
                    (credential_id, provider, label, key_fingerprint, status,
                     cool_down_until, consecutive_failures, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (credential_id) DO UPDATE SET
                        provider = EXCLUDED.provider,
                        label = EXCLUDED.label,
                        key_fingerprint = EXCLUDED.key_fingerprint,
                        status = EXCLUDED.status,
                        cool_down_until = EXCLUDED.cool_down_until,
                        consecutive_failures = EXCLUDED.consecutive_failures,
                        metadata = EXCLUDED.metadata
                    """,
                    (
                        cred.credential_id,
                        cred.provider,
                        cred.label,
                        cred.key_fingerprint,
                        cred.status,
                        cred.cool_down_until,
                        cred.consecutive_failures,
                        Json(cred.metadata),
                    ),
                )
            conn.commit()
        return len(credentials)
