from __future__ import annotations

import asyncio
import importlib
from datetime import datetime, timezone

import httpx
import pytest
from core.launcher_key_escrow import (
    EscrowConflictError,
    EscrowRecord,
    OpenBaoEscrowClient,
    SecretStoreUnavailableError,
)


def record(**changes: object) -> EscrowRecord:
    values = {
        "alias": "repo/customer-a",
        "token": "sk-secret-token",
        "team_id": "team-1",
        "litellm_key_id": None,
        "state": "pending",
        "schema_version": 1,
        "created_at": datetime(2026, 7, 23, tzinfo=timezone.utc),
    }
    values.update(changes)
    return EscrowRecord(**values)


def client(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    escrow = OpenBaoEscrowClient(
        http_client=http,
        address="https://bao.internal",
        kv_mount="launcher-kv",
        key_prefix="stable-keys",
        workload_token_supplier=lambda: "workload-token",
    )
    return escrow, http


@pytest.mark.asyncio
async def test_write_pending_uses_kv_v2_cas_zero_and_hashed_alias_path():
    seen = {}

    def handler(request: httpx.Request):
        seen["request"] = request
        return httpx.Response(200, json={"data": {"version": 1}})

    escrow, http = client(handler)
    try:
        await escrow.write_pending(record())
    finally:
        await http.aclose()

    request = seen["request"]
    assert request.url.path == (
        "/v1/launcher-kv/data/stable-keys/"
        "6cbe8cfb89ed79748484aadb3af916cbe428f63541bc5fca0838184c8ef3a803"
    )
    assert request.headers["X-Vault-Token"] == "workload-token"
    assert request.method == "POST"
    assert __import__("json").loads(request.content) == {
        "data": {
            "alias": "repo/customer-a",
            "token": "sk-secret-token",
            "team_id": "team-1",
            "litellm_key_id": None,
            "state": "pending",
            "schema_version": 1,
            "created_at": "2026-07-23T00:00:00+00:00",
        },
        "options": {"cas": 0},
    }


@pytest.mark.asyncio
async def test_read_decodes_kv_v2_record():
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={"data": {"data": record().to_dict(), "metadata": {"version": 3}}},
        )

    escrow, http = client(handler)
    try:
        assert await escrow.read("repo/customer-a") == record()
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_read_returns_none_for_missing_record():
    escrow, http = client(lambda request: httpx.Response(404, json={"errors": []}))
    try:
        assert await escrow.read("missing") is None
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_write_pending_reports_cas_conflict_without_secrets():
    def handler(request: httpx.Request):
        return httpx.Response(400, json={"errors": ["check-and-set failed for sk-secret-token"]})

    escrow, http = client(handler)
    try:
        with pytest.raises(EscrowConflictError) as exc:
            await escrow.write_pending(record())
    finally:
        await http.aclose()
    assert "sk-secret-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_auth_failure_is_typed_and_redacted():
    escrow, http = client(lambda request: httpx.Response(403, text="workload-token sk-secret-token"))
    try:
        with pytest.raises(SecretStoreUnavailableError) as exc:
            await escrow.read("repo/customer-a")
    finally:
        await http.aclose()
    assert exc.value.code == "secret_store_unavailable"
    assert "workload-token" not in str(exc.value)
    assert "sk-secret-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_timeout_is_typed_and_redacted():
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("timeout while sending sk-secret-token", request=request)

    escrow, http = client(handler)
    try:
        with pytest.raises(SecretStoreUnavailableError) as exc:
            await escrow.read("repo/customer-a")
    finally:
        await http.aclose()
    assert exc.value.code == "secret_store_unavailable"
    assert "sk-secret-token" not in str(exc.value)
    assert exc.value.__cause__ is None


@pytest.mark.asyncio
async def test_activate_preserves_secret_and_uses_current_version_as_cas():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={"data": {"data": record().to_dict(), "metadata": {"version": 7}}},
            )
        return httpx.Response(200, json={"data": {"version": 8}})

    escrow, http = client(handler)
    try:
        activated = await escrow.activate("repo/customer-a", "key-9")
    finally:
        await http.aclose()
    assert activated == record(state="active", litellm_key_id="key-9")
    body = __import__("json").loads(requests[1].content)
    assert body["options"] == {"cas": 7}
    assert body["data"]["token"] == "sk-secret-token"


@pytest.mark.asyncio
async def test_activate_rejects_stored_alias_mismatch_without_writing():
    requests = []

    def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "data": record(alias="repo/redirect-target").to_dict(),
                    "metadata": {"version": 7},
                }
            },
        )

    escrow, http = client(handler)
    try:
        with pytest.raises(EscrowConflictError):
            await escrow.activate("repo/customer-a", "key-9")
    finally:
        await http.aclose()

    assert [request.method for request in requests] == ["GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_supplier", [False, True])
async def test_token_supplier_failure_is_typed_redacted_and_unchained(async_supplier):
    secret = "supplier leaked workload-token"

    if async_supplier:
        async def supplier():
            raise RuntimeError(secret)
    else:
        def supplier():
            raise RuntimeError(secret)

    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("no request")))
    escrow = OpenBaoEscrowClient(
        http_client=http,
        address="https://bao.internal",
        kv_mount="launcher-kv",
        key_prefix="stable-keys",
        workload_token_supplier=supplier,
    )
    try:
        with pytest.raises(SecretStoreUnavailableError) as exc:
            await escrow.read("repo/customer-a")
    finally:
        await http.aclose()

    assert exc.value.code == "secret_store_unavailable"
    assert secret not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__ is True


@pytest.mark.asyncio
async def test_token_supplier_cancellation_is_preserved():
    async def supplier():
        raise asyncio.CancelledError

    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("no request")))
    escrow = OpenBaoEscrowClient(
        http_client=http,
        address="https://bao.internal",
        kv_mount="launcher-kv",
        key_prefix="stable-keys",
        workload_token_supplier=supplier,
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await escrow.read("repo/customer-a")
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_malformed_record_is_typed_redacted_and_unchained():
    secret = "malformed sk-secret-token"
    escrow, http = client(
        lambda request: httpx.Response(
            200,
            json={"data": {"data": {"alias": secret}, "metadata": {"version": 3}}},
        )
    )
    try:
        with pytest.raises(SecretStoreUnavailableError) as exc:
            await escrow.read("repo/customer-a")
    finally:
        await http.aclose()

    assert exc.value.code == "secret_store_unavailable"
    assert secret not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__ is True


@pytest.mark.asyncio
async def test_non_cas_bad_request_is_store_unavailable():
    escrow, http = client(
        lambda request: httpx.Response(400, json={"errors": ["invalid request"]})
    )
    try:
        with pytest.raises(SecretStoreUnavailableError) as exc:
            await escrow.write_pending(record())
    finally:
        await http.aclose()

    assert not isinstance(exc.value, EscrowConflictError)


def test_openbao_config_reports_typed_unavailable_when_required_setting_missing(monkeypatch):
    names = (
        "GATEWAY_ENGINE_OPENBAO_ADDR",
        "GATEWAY_ENGINE_OPENBAO_AUTH_MOUNT",
        "GATEWAY_ENGINE_OPENBAO_ROLE",
        "GATEWAY_ENGINE_OPENBAO_KV_MOUNT",
        "GATEWAY_ENGINE_OPENBAO_KEY_PREFIX",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    import core.config as config_mod

    mod = importlib.reload(config_mod)
    availability = mod.Config.secret_store_availability()
    assert availability.available is False
    assert availability.code == "secret_store_unavailable"
    assert "GATEWAY_ENGINE_OPENBAO_ADDR" in availability.missing_settings


def test_openbao_config_is_available_when_required_settings_exist(monkeypatch):
    values = {
        "GATEWAY_ENGINE_OPENBAO_ADDR": "https://bao.internal",
        "GATEWAY_ENGINE_OPENBAO_AUTH_MOUNT": "kubernetes",
        "GATEWAY_ENGINE_OPENBAO_ROLE": "gateway-engine",
        "GATEWAY_ENGINE_OPENBAO_KV_MOUNT": "launcher-kv",
        "GATEWAY_ENGINE_OPENBAO_KEY_PREFIX": "stable-keys",
        "GATEWAY_ENGINE_OPENBAO_TIMEOUT": "4.5",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    import core.config as config_mod

    mod = importlib.reload(config_mod)
    assert mod.Config.secret_store_availability().available is True
    assert mod.Config.OPENBAO_TIMEOUT == 4.5
