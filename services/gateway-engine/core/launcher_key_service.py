"""Transactional creation and recovery of stable launcher virtual keys."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx
from core.launcher_key_escrow import (
    EscrowConflictError,
    EscrowRecord,
    OpenBaoEscrowError,
)


class EscrowStore(Protocol):
    async def read(self, alias: str) -> EscrowRecord | None: ...

    async def write_pending(self, record: EscrowRecord) -> None: ...

    async def activate(self, alias: str, litellm_key_id: str) -> EscrowRecord: ...


class LauncherKeyServiceError(Exception):
    """A redacted, stable failure suitable for mapping at the API boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LauncherKeyResult:
    alias: str
    token: str
    team_id: str
    litellm_key_id: str


@dataclass(frozen=True)
class _RemoteKey:
    alias: str
    team_id: str
    key_id: str


def generate_virtual_key() -> str:
    """Return a LiteLLM-compatible virtual key using the operating-system CSPRNG."""

    return f"sk-{secrets.token_urlsafe(32)}"


class LauncherKeyService:
    def __init__(
        self,
        *,
        escrow: EscrowStore,
        litellm_http_client: httpx.AsyncClient,
        litellm_admin_url: str,
        litellm_master_key: str,
        token_factory: Callable[[], str] = generate_virtual_key,
    ) -> None:
        self._escrow = escrow
        self._http = litellm_http_client
        self._admin_url = litellm_admin_url.rstrip("/")
        self._master_key = litellm_master_key
        self._token_factory = token_factory

    def _master_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._master_key}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(
                method,
                f"{self._admin_url}/{path.lstrip('/')}",
                **kwargs,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            raise LauncherKeyServiceError("key_creation_incomplete", "LiteLLM key operation did not complete") from None

    @staticmethod
    def _remote_from(value: object) -> _RemoteKey | None:
        if not isinstance(value, Mapping):
            return None
        alias = value.get("key_alias") or value.get("key_name")
        team_id = value.get("team_id")
        key_id = value.get("key_id") or value.get("token")
        if not alias or not team_id or not key_id:
            return None
        return _RemoteKey(str(alias), str(team_id), str(key_id))

    async def _find_alias(self, alias: str) -> _RemoteKey | None:
        response = await self._request(
            "GET",
            "key/list",
            headers=self._master_headers(),
            params={"key_alias": alias},
        )
        if not response.is_success:
            raise LauncherKeyServiceError("key_creation_incomplete", "LiteLLM key lookup did not complete")
        try:
            body = response.json()
        except ValueError:
            body = None
        values = body if isinstance(body, list) else body.get("keys", []) if isinstance(body, Mapping) else []
        for value in values:
            remote = self._remote_from(value)
            if remote and remote.alias == alias:
                return remote
        return None

    async def _authenticate_token(self, token: str) -> _RemoteKey | None:
        response = await self._request("GET", "key/info", headers={"Authorization": f"Bearer {token}"})
        if response.status_code in (401, 403, 404):
            return None
        if not response.is_success:
            raise LauncherKeyServiceError("key_creation_incomplete", "LiteLLM key verification did not complete")
        try:
            body = response.json()
        except ValueError:
            return None
        value = body.get("info", body) if isinstance(body, Mapping) else None
        return self._remote_from(value)

    @staticmethod
    def _result(record: EscrowRecord) -> LauncherKeyResult:
        if not record.litellm_key_id:
            raise LauncherKeyServiceError("key_creation_incomplete", "Key creation is incomplete")
        return LauncherKeyResult(
            alias=record.alias,
            token=record.token,
            team_id=record.team_id,
            litellm_key_id=record.litellm_key_id,
        )

    @staticmethod
    def _identity_matches(record: EscrowRecord, remote: _RemoteKey) -> bool:
        return (
            record.alias == remote.alias and record.team_id == remote.team_id and record.litellm_key_id == remote.key_id
        )

    async def _read_escrow(self, alias: str) -> EscrowRecord | None:
        try:
            return await self._escrow.read(alias)
        except OpenBaoEscrowError:
            raise LauncherKeyServiceError("secret_store_unavailable", "Secret store is unavailable") from None

    async def _activate(self, alias: str, key_id: str) -> EscrowRecord:
        try:
            return await self._escrow.activate(alias, key_id)
        except OpenBaoEscrowError:
            raise LauncherKeyServiceError("key_creation_incomplete", "Key creation is incomplete") from None

    async def create_key(self, request: Mapping[str, object]) -> LauncherKeyResult:
        alias = str(request.get("key_alias") or "")
        team_id = str(request.get("team_id") or "")
        stored = await self._read_escrow(alias)
        if stored is not None:
            if stored.alias != alias or stored.team_id != team_id:
                raise LauncherKeyServiceError("key_identity_mismatch", "Stored key identity does not match")
            if stored.state != "pending":
                raise LauncherKeyServiceError("key_secret_not_escrowed", "Key alias already exists")
            verified = await self._authenticate_token(stored.token)
            if verified is None:
                await self._create_remote(request, stored.token)
                verified = await self._authenticate_token(stored.token)
            if verified is None or verified.alias != alias or verified.team_id != team_id:
                raise LauncherKeyServiceError("key_creation_incomplete", "Key verification did not complete")
            return self._result(await self._activate(alias, verified.key_id))

        if await self._find_alias(alias) is not None:
            raise LauncherKeyServiceError("key_secret_not_escrowed", "Key alias already exists without escrow")

        token = self._token_factory()
        pending = EscrowRecord(
            alias=alias,
            token=token,
            team_id=team_id,
            litellm_key_id=None,
            state="pending",
            schema_version=1,
            created_at=datetime.now(timezone.utc),
        )
        try:
            await self._escrow.write_pending(pending)
        except EscrowConflictError:
            raise LauncherKeyServiceError("key_creation_incomplete", "Concurrent key creation is incomplete") from None
        except OpenBaoEscrowError:
            raise LauncherKeyServiceError("secret_store_unavailable", "Secret store is unavailable") from None

        await self._create_remote(request, token)
        verified = await self._authenticate_token(token)
        if verified is None or verified.alias != alias or verified.team_id != team_id:
            raise LauncherKeyServiceError("key_creation_incomplete", "Key verification did not complete")
        return self._result(await self._activate(alias, verified.key_id))

    async def _create_remote(self, request: Mapping[str, object], token: str) -> None:
        body = dict(request)
        body["key"] = token
        response = await self._request("POST", "key/generate", headers=self._master_headers(), json=body)
        if not response.is_success:
            raise LauncherKeyServiceError("key_creation_incomplete", "LiteLLM key creation did not complete")

    async def recover_key(self, alias: str) -> LauncherKeyResult:
        remote = await self._find_alias(alias)
        if remote is None:
            raise LauncherKeyServiceError("key_alias_not_found", "Key alias was not found")
        stored = await self._read_escrow(alias)
        if stored is None or stored.state != "active":
            raise LauncherKeyServiceError("key_secret_not_escrowed", "Key secret is not escrowed")
        if not self._identity_matches(stored, remote):
            raise LauncherKeyServiceError("key_identity_mismatch", "Stored key identity does not match")
        return self._result(stored)

    async def import_key(self, alias: str, token: str) -> LauncherKeyResult:
        remote = await self._find_alias(alias)
        if remote is None:
            raise LauncherKeyServiceError("key_alias_not_found", "Key alias was not found")
        stored = await self._read_escrow(alias)
        if stored is not None:
            if stored.token != token or (stored.state == "active" and not self._identity_matches(stored, remote)):
                raise LauncherKeyServiceError("key_identity_mismatch", "Stored key identity does not match")
            if stored.state == "active":
                return self._result(stored)

        verified = await self._authenticate_token(token)
        if verified != remote:
            raise LauncherKeyServiceError("key_identity_mismatch", "Supplied token does not match key alias")
        if stored is None:
            pending = EscrowRecord(
                alias=alias,
                token=token,
                team_id=remote.team_id,
                litellm_key_id=None,
                state="pending",
                schema_version=1,
                created_at=datetime.now(timezone.utc),
            )
            try:
                await self._escrow.write_pending(pending)
            except OpenBaoEscrowError:
                raise LauncherKeyServiceError("secret_store_unavailable", "Secret store is unavailable") from None
        return self._result(await self._activate(alias, remote.key_id))
