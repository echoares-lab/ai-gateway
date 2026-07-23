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


class FakeEscrow:
    def __init__(self, stored=None, *, write_error=None):
        self.stored = stored
        self.write_error = write_error
        self.events = []

    async def read(self, alias):
        self.events.append(("read", alias))
        return self.stored

    async def write_pending(self, value):
        self.events.append(("write_pending", value))
        if self.write_error:
            raise self.write_error
        self.stored = value

    async def activate(self, alias, key_id):
        from dataclasses import replace

        self.events.append(("activate", alias, key_id))
        self.stored = replace(self.stored, state="active", litellm_key_id=key_id)
        return self.stored


def litellm_client(handler):
    return httpx.AsyncClient(
        base_url="http://litellm:4000",
        transport=httpx.MockTransport(handler),
    )


def service(escrow, http, tokens=None):
    from core.launcher_key_service import LauncherKeyService

    generated = iter(tokens or ["sk-generated-once"])
    return LauncherKeyService(
        escrow=escrow,
        litellm_http_client=http,
        litellm_admin_url="http://litellm:4000",
        litellm_master_key="master-key",
        token_factory=lambda: next(generated),
    )


def test_service_token_generation_uses_csprng_and_litellm_prefix(monkeypatch):
    from core import launcher_key_service

    monkeypatch.setattr(launcher_key_service.secrets, "token_urlsafe", lambda size: f"random-{size}")
    assert launcher_key_service.generate_virtual_key() == "sk-random-32"


@pytest.mark.asyncio
async def test_service_creation_writes_pending_before_exact_token_litellm_creation():
    escrow = FakeEscrow()
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/key/list":
            return httpx.Response(200, json=[])
        if request.url.path == "/key/generate":
            assert escrow.stored is not None
            body = __import__("json").loads(request.content)
            assert body["key"] == escrow.stored.token == "sk-stable-token"
            return httpx.Response(200, json={"key": "sk-stable-token", "key_id": "key-9"})
        assert request.url.path == "/key/info"
        assert request.headers["Authorization"] == "Bearer sk-stable-token"
        return httpx.Response(
            200,
            json={"info": {"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}},
        )

    http = litellm_client(handler)
    try:
        result = await service(escrow, http, ["sk-stable-token"]).create_key(
            {"key_alias": "repo/customer-a", "team_id": "team-1", "models": ["gpt-5"]}
        )
    finally:
        await http.aclose()

    assert result.token == "sk-stable-token"
    assert result.litellm_key_id == "key-9"
    assert escrow.stored.state == "active"
    assert [request.url.path for request in requests] == ["/key/list", "/key/generate", "/key/info"]


@pytest.mark.asyncio
async def test_service_openbao_failure_prevents_litellm_creation():
    from core.launcher_key_service import LauncherKeyServiceError

    escrow = FakeEscrow(write_error=SecretStoreUnavailableError("unavailable"))
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/key/list"
        return httpx.Response(200, json=[])

    http = litellm_client(handler)
    try:
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service(escrow, http).create_key({"key_alias": "repo/customer-a", "team_id": "team-1"})
    finally:
        await http.aclose()
    assert exc.value.code == "secret_store_unavailable"
    assert not [request for request in requests if request.url.path == "/key/generate"]


@pytest.mark.asyncio
async def test_service_litellm_failure_leaves_pending_without_returning_token():
    from core.launcher_key_service import LauncherKeyServiceError

    escrow = FakeEscrow()

    def handler(request):
        if request.url.path == "/key/list":
            return httpx.Response(200, json=[])
        return httpx.Response(503, json={"error": "failed sk-do-not-echo"})

    http = litellm_client(handler)
    try:
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service(escrow, http, ["sk-stable-token"]).create_key(
                {"key_alias": "repo/customer-a", "team_id": "team-1"}
            )
    finally:
        await http.aclose()
    assert exc.value.code == "key_creation_incomplete"
    assert "sk-stable-token" not in str(exc.value)
    assert escrow.stored.state == "pending"


@pytest.mark.asyncio
async def test_service_retry_resumes_pending_with_same_token_without_generating_another():
    escrow = FakeEscrow(record(token="sk-original-token"))
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/key/info"
        assert request.headers["Authorization"] == "Bearer sk-original-token"
        return httpx.Response(
            200,
            json={"info": {"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}},
        )

    http = litellm_client(handler)
    try:
        result = await service(escrow, http, []).create_key({"key_alias": "repo/customer-a", "team_id": "team-1"})
    finally:
        await http.aclose()
    assert result.token == "sk-original-token"
    assert [request.url.path for request in requests] == ["/key/info"]
    assert escrow.stored.state == "active"


@pytest.mark.asyncio
async def test_service_retry_recreates_missing_remote_with_exact_pending_token():
    escrow = FakeEscrow(record(token="sk-original-token"))
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/key/info" and len(requests) == 1:
            return httpx.Response(401, json={"error": "not found"})
        if request.url.path == "/key/generate":
            assert __import__("json").loads(request.content)["key"] == "sk-original-token"
            return httpx.Response(200, json={"key_id": "key-9"})
        return httpx.Response(
            200,
            json={"info": {"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}},
        )

    http = litellm_client(handler)
    try:
        result = await service(escrow, http, []).create_key({"key_alias": "repo/customer-a", "team_id": "team-1"})
    finally:
        await http.aclose()
    assert result.token == "sk-original-token"
    assert [request.url.path for request in requests] == ["/key/info", "/key/generate", "/key/info"]


@pytest.mark.asyncio
async def test_service_verification_failure_keeps_pending_and_redacts_token():
    from core.launcher_key_service import LauncherKeyServiceError

    escrow = FakeEscrow()

    def handler(request):
        if request.url.path == "/key/list":
            return httpx.Response(200, json=[])
        if request.url.path == "/key/generate":
            return httpx.Response(200, json={"key": "sk-stable-token", "key_id": "key-9"})
        return httpx.Response(200, json={"info": {"key_alias": "other", "team_id": "team-1", "key_id": "key-9"}})

    http = litellm_client(handler)
    try:
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service(escrow, http, ["sk-stable-token"]).create_key(
                {"key_alias": "repo/customer-a", "team_id": "team-1"}
            )
    finally:
        await http.aclose()
    assert exc.value.code == "key_creation_incomplete"
    assert "sk-stable-token" not in str(exc.value)
    assert escrow.stored.state == "pending"


@pytest.mark.asyncio
async def test_service_existing_remote_alias_is_not_rotated_or_escrowed():
    from core.launcher_key_service import LauncherKeyServiceError

    escrow = FakeEscrow()
    http = litellm_client(
        lambda request: httpx.Response(
            200, json=[{"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "old-key"}]
        )
    )
    try:
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service(escrow, http, []).create_key({"key_alias": "repo/customer-a", "team_id": "team-1"})
    finally:
        await http.aclose()
    assert exc.value.code == "key_secret_not_escrowed"
    assert not [event for event in escrow.events if event[0] == "write_pending"]


@pytest.mark.asyncio
async def test_service_recovery_checks_remote_and_escrow_identity():
    escrow = FakeEscrow(record(state="active", litellm_key_id="key-9"))
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/key/list":
            return httpx.Response(200, json=[{"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}])
        assert request.headers["Authorization"] == "Bearer sk-secret-token"
        return httpx.Response(
            200, json={"info": {"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}}
        )

    http = litellm_client(handler)
    try:
        result = await service(escrow, http).recover_key("repo/customer-a")
    finally:
        await http.aclose()
    assert result.token == "sk-secret-token"
    assert [request.url.path for request in requests] == ["/key/list", "/key/info"]


@pytest.mark.asyncio
async def test_service_recovery_refuses_swapped_escrow_token_without_disclosing_it():
    from core.launcher_key_service import LauncherKeyServiceError

    escrow = FakeEscrow(record(token="sk-swapped-token", state="active", litellm_key_id="key-9"))

    def handler(request):
        if request.url.path == "/key/list":
            return httpx.Response(200, json=[{"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}])
        assert request.headers["Authorization"] == "Bearer sk-swapped-token"
        return httpx.Response(
            200, json={"info": {"key_alias": "repo/customer-b", "team_id": "team-2", "key_id": "key-8"}}
        )

    http = litellm_client(handler)
    try:
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service(escrow, http).recover_key("repo/customer-a")
    finally:
        await http.aclose()
    assert exc.value.code == "key_identity_mismatch"
    assert "sk-swapped-token" not in str(exc.value)


@pytest.mark.asyncio
async def test_service_recovery_returns_stable_missing_and_mismatch_codes():
    from core.launcher_key_service import LauncherKeyServiceError

    cases = [
        ([], record(state="active", litellm_key_id="key-9"), "key_alias_not_found"),
        ([{"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}], None, "key_secret_not_escrowed"),
        (
            [{"key_alias": "repo/customer-a", "team_id": "team-2", "key_id": "key-9"}],
            record(state="active", litellm_key_id="key-9"),
            "key_identity_mismatch",
        ),
    ]
    for remote, stored, code in cases:
        escrow = FakeEscrow(stored)
        http = litellm_client(lambda request, remote=remote: httpx.Response(200, json=remote))
        try:
            with pytest.raises(LauncherKeyServiceError) as exc:
                await service(escrow, http).recover_key("repo/customer-a")
        finally:
            await http.aclose()
        assert exc.value.code == code


@pytest.mark.asyncio
async def test_service_legacy_import_authenticates_token_then_escrows_active_identity():
    escrow = FakeEscrow()

    def handler(request):
        if request.url.path == "/key/list":
            return httpx.Response(200, json=[{"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}])
        assert request.headers["Authorization"] == "Bearer sk-legacy-token"
        return httpx.Response(
            200, json={"info": {"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}}
        )

    http = litellm_client(handler)
    try:
        result = await service(escrow, http).import_key("repo/customer-a", "sk-legacy-token")
    finally:
        await http.aclose()
    assert result.token == "sk-legacy-token"
    assert escrow.stored.state == "active"
    assert escrow.stored.litellm_key_id == "key-9"


@pytest.mark.asyncio
async def test_service_legacy_import_refuses_different_active_secret():
    from core.launcher_key_service import LauncherKeyServiceError

    escrow = FakeEscrow(record(token="sk-existing", state="active", litellm_key_id="key-9"))
    http = litellm_client(
        lambda request: httpx.Response(
            200, json=[{"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}]
        )
    )
    try:
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service(escrow, http).import_key("repo/customer-a", "sk-different")
    finally:
        await http.aclose()
    assert exc.value.code == "key_identity_mismatch"
    assert not [event for event in escrow.events if event[0] == "write_pending"]


@pytest.mark.asyncio
async def test_service_legacy_import_refuses_pending_record_identity_mismatch():
    from core.launcher_key_service import LauncherKeyServiceError

    escrow = FakeEscrow(record(token="sk-legacy-token", team_id="team-other", litellm_key_id="key-other"))

    def handler(request):
        if request.url.path == "/key/list":
            return httpx.Response(200, json=[{"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}])
        return httpx.Response(
            200, json={"info": {"key_alias": "repo/customer-a", "team_id": "team-1", "key_id": "key-9"}}
        )

    http = litellm_client(handler)
    try:
        with pytest.raises(LauncherKeyServiceError) as exc:
            await service(escrow, http).import_key("repo/customer-a", "sk-legacy-token")
    finally:
        await http.aclose()
    assert exc.value.code == "key_identity_mismatch"
    assert "sk-legacy-token" not in str(exc.value)
    assert not [event for event in escrow.events if event[0] == "activate"]


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
        "/v1/launcher-kv/data/stable-keys/6cbe8cfb89ed79748484aadb3af916cbe428f63541bc5fca0838184c8ef3a803"
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
    escrow, http = client(lambda request: httpx.Response(400, json={"errors": ["invalid request"]}))
    try:
        with pytest.raises(SecretStoreUnavailableError) as exc:
            await escrow.write_pending(record())
    finally:
        await http.aclose()

    assert not isinstance(exc.value, EscrowConflictError)


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [["check-and-set failed"], "check-and-set failed"])
async def test_non_object_bad_request_is_store_unavailable(body):
    escrow, http = client(lambda request: httpx.Response(400, json=body))
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
