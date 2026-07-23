"""Mock integration coverage for stable launcher-key escrow transactions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from core.launcher_key_escrow import OpenBaoEscrowClient
from core.launcher_key_service import LauncherKeyService, LauncherKeyServiceError

pytestmark = [pytest.mark.mock, pytest.mark.asyncio]

ALIAS = "repo/integration-customer"
TEAM_ID = "team-integration"
STABLE_TOKEN = "sk-integration-stable-token-do-not-log"
LEGACY_TOKEN = "sk-integration-legacy-token-do-not-log"


@dataclass
class MockKeyBackends:
    escrow_record: dict[str, Any] | None = None
    escrow_version: int = 0
    remote_keys: dict[str, dict[str, str]] = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)
    generate_calls: int = 0
    fail_activation_once: bool = False
    fail_pending_write_once: bool = False
    fail_pending_cas_once: bool = False
    fail_generate_response_once: bool = False
    fail_escrow_read_once: bool = False
    fail_litellm_list_once: bool = False
    fail_litellm_info_once: bool = False

    def seed_remote(self, alias: str, token: str, key_id: str = "key-legacy") -> None:
        self.remote_keys[alias] = {
            "key_alias": alias,
            "team_id": TEAM_ID,
            "key_id": key_id,
            "token": token,
        }

    @property
    def delete_requests(self) -> list[tuple[str, str]]:
        return [request for request in self.requests if request[0] == "DELETE"]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.url.host == "bao.test":
            return self._openbao(request)
        if request.url.host == "litellm.test":
            return self._litellm(request)
        return httpx.Response(500, json={"error": "unexpected host"})

    def _openbao(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if self.fail_escrow_read_once:
                self.fail_escrow_read_once = False
                return httpx.Response(503, json={"errors": ["temporarily unavailable"]})
            if self.escrow_record is None:
                return httpx.Response(404, json={"errors": []})
            return httpx.Response(
                200,
                json={
                    "data": {
                        "data": self.escrow_record,
                        "metadata": {"version": self.escrow_version},
                    }
                },
            )
        if request.method == "POST":
            body = json.loads(request.read())
            record = body["data"]
            if record["state"] == "pending" and self.fail_pending_write_once:
                self.fail_pending_write_once = False
                return httpx.Response(503, json={"errors": ["temporarily unavailable"]})
            if record["state"] == "pending" and self.fail_pending_cas_once:
                self.fail_pending_cas_once = False
                return httpx.Response(
                    400,
                    json={"errors": ["check-and-set parameter did not match current version"]},
                )
            if record["state"] == "active" and self.fail_activation_once:
                self.fail_activation_once = False
                return httpx.Response(503, json={"errors": ["temporarily unavailable"]})
            self.escrow_record = record
            self.escrow_version += 1
            return httpx.Response(200, json={"data": {"version": self.escrow_version}})
        return httpx.Response(405)

    def _litellm(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/key/list":
            if self.fail_litellm_list_once:
                self.fail_litellm_list_once = False
                return httpx.Response(503, json={"error": "temporarily unavailable"})
            alias = request.url.params.get("key_alias")
            remote = self.remote_keys.get(alias or "")
            return httpx.Response(200, json={"keys": [remote] if remote else []})
        if request.method == "POST" and request.url.path == "/key/generate":
            body = json.loads(request.read())
            self.generate_calls += 1
            self.seed_remote(body["key_alias"], body["key"], key_id="key-created")
            if self.fail_generate_response_once:
                self.fail_generate_response_once = False
                return httpx.Response(503, json={"error": "response lost after creation"})
            return httpx.Response(200, json={"key": body["key"]})
        if request.method == "GET" and request.url.path == "/key/info":
            if self.fail_litellm_info_once:
                self.fail_litellm_info_once = False
                return httpx.Response(503, json={"error": "temporarily unavailable"})
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            remote = next(
                (value for value in self.remote_keys.values() if value["token"] == token),
                None,
            )
            if remote is None:
                return httpx.Response(401, json={"error": "invalid key"})
            return httpx.Response(200, json={"info": remote})
        return httpx.Response(404, json={"error": "unexpected LiteLLM request"})


def build_service(backends: MockKeyBackends, token: str = STABLE_TOKEN):
    http = httpx.AsyncClient(transport=httpx.MockTransport(backends))
    escrow = OpenBaoEscrowClient(
        http_client=http,
        address="https://bao.test",
        kv_mount="kv",
        key_prefix="launcher-keys",
        workload_token_supplier=lambda: "openbao-workload-token-do-not-log",
    )
    service = LauncherKeyService(
        escrow=escrow,
        litellm_http_client=http,
        litellm_admin_url="https://litellm.test",
        litellm_master_key="litellm-master-token-do-not-log",
        token_factory=lambda: token,
    )
    return service, http


async def test_create_local_loss_then_recover_returns_exact_same_token() -> None:
    backends = MockKeyBackends()
    service, http = build_service(backends)
    try:
        created = await service.create_key({"key_alias": ALIAS, "team_id": TEAM_ID})
        del created  # simulate launcher losing its local cache entry

        recovered = await service.recover_key(ALIAS)

        assert recovered.token == STABLE_TOKEN
        assert recovered.litellm_key_id == "key-created"
        assert backends.generate_calls == 1
        assert not backends.delete_requests
    finally:
        await http.aclose()


async def test_pre_escrow_key_import_then_recover_returns_exact_token() -> None:
    backends = MockKeyBackends()
    backends.seed_remote(ALIAS, LEGACY_TOKEN)
    service, http = build_service(backends)
    try:
        imported = await service.import_key(ALIAS, LEGACY_TOKEN)
        recovered = await service.recover_key(ALIAS)

        assert imported.token == recovered.token == LEGACY_TOKEN
        assert backends.generate_calls == 0
        assert not backends.delete_requests
    finally:
        await http.aclose()


@pytest.mark.parametrize(
    "failure,backend_options,expected_code",
    [
        ("initial escrow read", {"fail_escrow_read_once": True}, "secret_store_unavailable"),
        ("pending write", {"fail_pending_write_once": True}, "secret_store_unavailable"),
        ("pending CAS", {"fail_pending_cas_once": True}, "key_creation_incomplete"),
        ("LiteLLM generate", {"fail_generate_response_once": True}, "key_creation_incomplete"),
        ("post-generate verification", {"fail_litellm_info_once": True}, "key_creation_incomplete"),
        ("activation", {"fail_activation_once": True}, "key_creation_incomplete"),
    ],
)
async def test_every_recoverable_create_boundary_retries_exact_token_without_duplicate_or_delete(
    failure: str,
    backend_options: dict[str, bool],
    expected_code: str,
) -> None:
    backends = MockKeyBackends(**backend_options)
    service, http = build_service(backends)
    try:
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service.create_key({"key_alias": ALIAS, "team_id": TEAM_ID})
        assert exc.value.code == expected_code, failure

        recovered = await service.create_key({"key_alias": ALIAS, "team_id": TEAM_ID})

        assert recovered.token == STABLE_TOKEN
        assert backends.remote_keys[ALIAS]["token"] == STABLE_TOKEN
        assert backends.generate_calls == 1
        assert not backends.delete_requests
    finally:
        await http.aclose()


@pytest.mark.parametrize(
    "backend_options,expected_code",
    [
        ({"fail_pending_write_once": True}, "secret_store_unavailable"),
        ({"fail_activation_once": True}, "key_creation_incomplete"),
    ],
)
async def test_every_recoverable_import_boundary_retries_exact_token_without_create_or_delete(
    backend_options: dict[str, bool],
    expected_code: str,
) -> None:
    backends = MockKeyBackends(**backend_options)
    backends.seed_remote(ALIAS, LEGACY_TOKEN)
    service, http = build_service(backends)
    try:
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service.import_key(ALIAS, LEGACY_TOKEN)
        assert exc.value.code == expected_code

        recovered = await service.import_key(ALIAS, LEGACY_TOKEN)

        assert recovered.token == LEGACY_TOKEN
        assert backends.remote_keys[ALIAS]["token"] == LEGACY_TOKEN
        assert backends.generate_calls == 0
        assert not backends.delete_requests
    finally:
        await http.aclose()


@pytest.mark.parametrize(
    "failure",
    ["escrow_read", "litellm_lookup", "litellm_verification"],
)
async def test_every_recoverable_recovery_boundary_never_creates_or_deletes(
    failure: str,
) -> None:
    backends = MockKeyBackends()
    service, http = build_service(backends)
    try:
        await service.create_key({"key_alias": ALIAS, "team_id": TEAM_ID})
        if failure == "escrow_read":
            backends.fail_escrow_read_once = True
        elif failure == "litellm_lookup":
            backends.fail_litellm_list_once = True
        else:
            backends.fail_litellm_info_once = True
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service.recover_key(ALIAS)
        assert exc.value.code in {"secret_store_unavailable", "key_creation_incomplete"}
        result = await service.recover_key(ALIAS)

        assert result.token == STABLE_TOKEN
        assert backends.remote_keys[ALIAS]["token"] == STABLE_TOKEN
        assert backends.generate_calls == 1
        assert not backends.delete_requests
    finally:
        await http.aclose()


async def test_logs_never_expose_tokens_or_authorization_headers(caplog) -> None:
    backends = MockKeyBackends()
    service, http = build_service(backends)
    caplog.set_level(logging.DEBUG)
    try:
        await service.create_key({"key_alias": ALIAS, "team_id": TEAM_ID})
        await service.recover_key(ALIAS)
    finally:
        await http.aclose()

    captured = caplog.text.lower()
    for secret in (
        STABLE_TOKEN,
        "openbao-workload-token-do-not-log",
        "litellm-master-token-do-not-log",
    ):
        assert secret.lower() not in captured
    for header_name in ("authorization", "x-vault-token"):
        assert header_name not in captured
