import logging
from unittest.mock import AsyncMock, patch

import core.admin_shared as admin_shared
import httpx
import pytest
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
    mock_response = {"key": "sk-123"}
    key_data = {"team_id": "team-1"}

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(200, json=mock_response)

        response = client.post("/admin/keys", headers={"x-admin-key": admin_key}, json=key_data)

        assert response.status_code == 200
        assert response.json() == mock_response


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
