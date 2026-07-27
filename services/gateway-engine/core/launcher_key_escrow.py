"""OpenBao KV-v2 storage for launcher-managed virtual-key secrets."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Awaitable, Callable, cast

import httpx

TokenSupplier = Callable[[], str | Awaitable[str]]


@dataclass(frozen=True)
class EscrowRecord:
    alias: str
    token: str
    team_id: str
    litellm_key_id: str | None
    state: str
    schema_version: int
    created_at: datetime

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["created_at"] = self.created_at.isoformat()
        return result

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "EscrowRecord":
        return cls(
            alias=str(value["alias"]),
            token=str(value["token"]),
            team_id=str(value["team_id"]),
            litellm_key_id=(str(value["litellm_key_id"]) if value.get("litellm_key_id") is not None else None),
            state=str(value["state"]),
            schema_version=int(value["schema_version"]),
            created_at=datetime.fromisoformat(str(value["created_at"])),
        )


class OpenBaoEscrowError(Exception):
    code = "secret_store_unavailable"


class SecretStoreUnavailableError(OpenBaoEscrowError):
    """OpenBao could not be accessed safely."""


class EscrowConflictError(OpenBaoEscrowError):
    """A KV-v2 check-and-set operation conflicted with another writer."""


class OpenBaoEscrowClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        address: str,
        kv_mount: str,
        key_prefix: str,
        workload_token_supplier: TokenSupplier,
        timeout: float = 5.0,
    ) -> None:
        self._http = http_client
        self._address = address.rstrip("/")
        self._kv_mount = kv_mount.strip("/")
        self._key_prefix = key_prefix.strip("/")
        self._token_supplier = workload_token_supplier
        self._timeout = timeout

    @staticmethod
    def alias_digest(alias: str) -> str:
        return hashlib.sha256(alias.encode("utf-8")).hexdigest()

    def _url(self, alias: str) -> str:
        digest = self.alias_digest(alias)
        return f"{self._address}/v1/{self._kv_mount}/data/{self._key_prefix}/{digest}"

    async def _headers(self) -> dict[str, str]:
        try:
            token = self._token_supplier()
            if inspect.isawaitable(token):
                token = await token
        except asyncio.CancelledError:
            raise
        except Exception:
            raise SecretStoreUnavailableError("secret store authentication unavailable") from None
        if not token:
            raise SecretStoreUnavailableError("secret store authentication unavailable")
        return {"X-Vault-Token": cast(str, token)}

    async def _request(self, method: str, alias: str, **kwargs: object) -> httpx.Response:
        try:
            response = await self._http.request(
                method,
                self._url(alias),
                headers=await self._headers(),
                timeout=self._timeout,
                **kwargs,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            raise SecretStoreUnavailableError("secret store request failed") from None
        if response.status_code in (401, 403):
            raise SecretStoreUnavailableError("secret store authentication failed")
        return response

    async def _read_versioned(self, alias: str) -> tuple[EscrowRecord, int] | None:
        response = await self._request("GET", alias)
        if response.status_code == 404:
            return None
        if not response.is_success:
            raise SecretStoreUnavailableError("secret store read failed")
        try:
            envelope = response.json()["data"]
            return EscrowRecord.from_dict(envelope["data"]), int(envelope["metadata"]["version"])
        except (KeyError, TypeError, ValueError):
            raise SecretStoreUnavailableError("secret store returned an invalid record") from None

    async def read(self, alias: str) -> EscrowRecord | None:
        versioned = await self._read_versioned(alias)
        return versioned[0] if versioned else None

    async def _write(self, record: EscrowRecord, cas: int) -> None:
        response = await self._request(
            "POST",
            record.alias,
            json={"data": record.to_dict(), "options": {"cas": cas}},
        )
        if response.status_code == 400:
            try:
                body = response.json()
            except ValueError:
                body = None
            errors = body.get("errors", []) if isinstance(body, Mapping) else []
            is_cas_conflict = isinstance(errors, list) and any(
                isinstance(error, str) and "check-and-set" in error.lower() for error in errors
            )
            if is_cas_conflict:
                raise EscrowConflictError("secret store write conflict")
            raise SecretStoreUnavailableError("secret store write failed")
        if not response.is_success:
            raise SecretStoreUnavailableError("secret store write failed")

    async def write_pending(self, record: EscrowRecord) -> None:
        if record.state != "pending":
            raise ValueError("escrow record must be pending")
        await self._write(record, cas=0)

    async def activate(self, alias: str, litellm_key_id: str) -> EscrowRecord:
        versioned = await self._read_versioned(alias)
        if versioned is None:
            raise EscrowConflictError("escrow record does not exist")
        record, version = versioned
        if record.alias != alias:
            raise EscrowConflictError("escrow record alias mismatch")
        activated = replace(record, state="active", litellm_key_id=litellm_key_id)
        await self._write(activated, cas=version)
        return activated
