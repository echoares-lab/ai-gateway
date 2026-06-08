import pytest
import httpx
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@pytest.fixture
def admin_key(monkeypatch):
    key = "test-admin-key"
    monkeypatch.setenv("ADMIN_API_KEY", key)
    return key

@pytest.mark.asyncio
async def test_admin_teams_list_unauthorized(admin_key):
    # Wrong key
    response = client.get("/admin/teams", headers={"x-admin-key": "wrong-key"})
    assert response.status_code == 403

@pytest.mark.asyncio
async def test_admin_api_key_missing(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "")
    response = client.get("/admin/teams", headers={"x-admin-key": "any"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "admin_key_missing"

@pytest.mark.asyncio
async def test_admin_teams_list_success(admin_key):
    mock_response = {
        "data": [
            {"team_id": "team-1", "team_alias": "Team 1"}
        ]
    }

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(
            200,
            json=mock_response
        )

        response = client.get(
            "/admin/teams",
            headers={"x-admin-key": admin_key}
        )

        assert response.status_code == 200
        assert response.json() == mock_response
        # Check that it called LiteLLM
        assert mock_request.called

@pytest.mark.asyncio
async def test_admin_teams_create_success(admin_key):
    mock_response = {"team_id": "new-team"}
    team_data = {"team_alias": "New Team"}

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_request:
        mock_request.return_value = httpx.Response(
            201,
            json=mock_response
        )

        response = client.post(
            "/admin/teams",
            headers={"x-admin-key": admin_key},
            json=team_data
        )

        assert response.status_code == 201
        assert response.json() == mock_response

@pytest.mark.asyncio
async def test_onboarding_validate_success(admin_key):
    # Mocking httpx.AsyncClient.get for the probe call
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(200)

        response = client.post(
            "/onboarding/validate",
            headers={"x-admin-key": admin_key},
            json={"key": "sk-123"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "connected"
        assert mock_get.called
