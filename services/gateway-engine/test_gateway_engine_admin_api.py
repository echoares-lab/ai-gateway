import logging
from unittest.mock import AsyncMock, patch

import core.admin_shared as admin_shared
import httpx
import pytest
from core.launcher_key_service import LauncherKeyResult, LauncherKeyServiceError
from core.onboarding.onboarding_service import OnboardingService
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.fixture
def admin_key(monkeypatch):
    key = "test-admin-key"
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", key)
    return key


@pytest.mark.asyncio
async def test_admin_read_auth_optional(monkeypatch):
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "read-admin")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_READ_AUTH", "true")
    response = client.get("/admin/status")
    assert response.status_code == 403
    response = client.get("/admin/status", headers={"x-admin-key": "read-admin"})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_read_auth_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GATEWAY_ENGINE_ADMIN_READ_AUTH", raising=False)
    response = client.get("/admin/status")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_teams_list_unauthorized(admin_key):
    # Wrong key
    response = client.get("/admin/teams", headers={"x-admin-key": "wrong-key"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_api_key_missing(monkeypatch):
    monkeypatch.delenv("GATEWAY_ENGINE_ADMIN_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    response = client.get("/admin/teams", headers={"x-admin-key": "any"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "admin_key_required"


@pytest.mark.asyncio
async def test_admin_api_key_legacy_alias_warns(monkeypatch, caplog):
    monkeypatch.delenv("GATEWAY_ENGINE_ADMIN_KEY", raising=False)
    monkeypatch.setenv("ADMIN_API_KEY", "legacy-admin")
    monkeypatch.setattr(admin_shared, "_legacy_admin_key_warned", False)
    caplog.set_level(logging.WARNING, logger="gateway-engine.admin")

    mock_response = {"data": []}

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(200, json=mock_response)

        response = client.get("/admin/teams", headers={"x-admin-key": "legacy-admin"})

    assert response.status_code == 200
    assert response.json() == mock_response
    assert "ADMIN_API_KEY is deprecated" in caplog.text


@pytest.mark.asyncio
async def test_admin_teams_list_success(admin_key):
    mock_response = {"data": [{"team_id": "team-1", "team_alias": "Team 1"}]}

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(200, json=mock_response)

        response = client.get("/admin/teams", headers={"x-admin-key": admin_key})

        assert response.status_code == 200
        assert response.json() == mock_response
        # Check that it called LiteLLM
        assert mock_request.called


@pytest.mark.asyncio
async def test_admin_teams_create_success(admin_key):
    mock_response = {"team_id": "new-team"}
    team_data = {"team_alias": "New Team"}

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(201, json=mock_response)

        response = client.post("/admin/teams", headers={"x-admin-key": admin_key}, json=team_data)

        assert response.status_code == 201
        assert response.json() == mock_response


@pytest.mark.asyncio
async def test_admin_keys_create_success(admin_key):
    result = LauncherKeyResult("repo/customer-a", "sk-123", "team-1", "key-9")
    service = AsyncMock()
    service.create_key.return_value = result
    key_data = {"key_alias": "repo/customer-a", "team_id": "team-1", "models": ["gpt-5"]}

    with patch("admin_api._launcher_key_service", return_value=service):
        response = client.post("/admin/keys", headers={"x-admin-key": admin_key}, json=key_data)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "key_alias": "repo/customer-a",
        "key": "sk-123",
        "team_id": "team-1",
        "key_id": "key-9",
    }
    service.create_key.assert_awaited_once_with(key_data)


@pytest.mark.parametrize("path", ["secret", "import"])
def test_admin_key_secret_routes_require_admin_key(admin_key, path):
    method = client.get if path == "secret" else client.post
    kwargs = {} if path == "secret" else {"json": {"key": "sk-private"}}
    response = method(f"/admin/keys/repo/customer-a/{path}", headers={"x-admin-key": "wrong"}, **kwargs)

    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert "sk-private" not in response.text


@pytest.mark.parametrize("alias", ["%2E%2E", "repo//customer", "repo/customer%20a"])
def test_admin_key_secret_rejects_invalid_path_alias(admin_key, alias):
    response = client.get(f"/admin/keys/{alias}/secret", headers={"x-admin-key": admin_key})

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


def test_admin_key_secret_recovers_slash_alias(admin_key):
    service = AsyncMock()
    service.recover_key.return_value = LauncherKeyResult("repo/customer-a", "sk-original", "team-1", "key-9")

    with patch("admin_api._launcher_key_service", return_value=service):
        response = client.get("/admin/keys/repo/customer-a/secret", headers={"x-admin-key": admin_key})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "key_alias": "repo/customer-a",
        "key": "sk-original",
        "team_id": "team-1",
        "key_id": "key-9",
    }
    service.recover_key.assert_awaited_once_with("repo/customer-a")


def test_admin_key_import_verifies_and_returns_token(admin_key):
    service = AsyncMock()
    service.import_key.return_value = LauncherKeyResult("repo/customer-a", "sk-legacy", "team-1", "key-9")

    with patch("admin_api._launcher_key_service", return_value=service):
        response = client.post(
            "/admin/keys/repo/customer-a/import",
            headers={"x-admin-key": admin_key},
            json={"key": "sk-legacy"},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["key"] == "sk-legacy"
    service.import_key.assert_awaited_once_with("repo/customer-a", "sk-legacy")


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("key_alias_not_found", 404),
        ("key_secret_not_escrowed", 409),
        ("key_identity_mismatch", 409),
        ("secret_store_unavailable", 503),
        ("key_creation_incomplete", 502),
    ],
)
def test_admin_key_errors_have_typed_status_and_redacted_body(admin_key, code, status):
    service = AsyncMock()
    service.recover_key.side_effect = LauncherKeyServiceError(code, "redacted failure")

    with patch("admin_api._launcher_key_service", return_value=service):
        response = client.get("/admin/keys/repo/customer-a/secret", headers={"x-admin-key": admin_key})

    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] != "redacted failure"


def test_admin_key_import_error_never_echoes_supplied_token(admin_key):
    token = "sk-must-never-leak"
    service = AsyncMock()
    service.import_key.side_effect = LauncherKeyServiceError("key_identity_mismatch", f"mismatch: {token}")

    with patch("admin_api._launcher_key_service", return_value=service):
        response = client.post(
            "/admin/keys/repo/customer-a/import",
            headers={"x-admin-key": admin_key},
            json={"key": token},
        )

    assert response.status_code == 409
    assert token not in response.text
    assert response.json()["error"]["code"] == "key_identity_mismatch"


def test_admin_key_import_validation_is_no_store_and_redacted(admin_key):
    response = client.post(
        "/admin/keys/repo/customer-a/import",
        headers={"x-admin-key": admin_key},
        json={"key": {"secret": "sk-nested-must-not-leak"}},
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert "sk-nested-must-not-leak" not in response.text


def test_admin_key_create_auth_precedes_body_validation(admin_key):
    response = client.post("/admin/keys", headers={"x-admin-key": "wrong"}, content=b"not-json")

    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_onboarding_service_uses_gateway_engine_admin_key(monkeypatch):
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "gateway-admin")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "litellm-master")

    service = OnboardingService()

    team_response = httpx.Response(
        200,
        json={"team_id": "team-1"},
        request=httpx.Request("POST", "http://litellm:4000/team/new"),
    )
    key_response = httpx.Response(
        200,
        json={"key": "sk-tenant"},
        request=httpx.Request("POST", "http://litellm:4000/key/generate"),
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [team_response, key_response]

        result = await service.register_tenant(
            tenant_id="tenant-1",
            email="ops@example.com",
            plan_id="default",
        )

    assert result == {
        "success": True,
        "tenant_id": "tenant-1",
        "api_key": "sk-tenant",
        "team_id": "team-1",
    }
