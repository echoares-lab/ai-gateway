import pytest
from httpx import AsyncClient
import httpx # Add this line
from main import app
from core.onboarding.onboarding_service import onboarding_service
import os

@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "mock-master-key")
    monkeypatch.setenv("ADMIN_API_KEY", "mock-admin-key")
    monkeypatch.setenv("LITELLM_ADMIN_URL", "http://mock-litellm")

@pytest.fixture
def mock_httpx_responses(respx_mock):
    # Mock LiteLLM team creation
    respx_mock.post("http://mock-litellm/team/new").mock(
        return_value=httpx.Response(200, json={"team_id": "new-tenant-id"})
    )
    # Mock LiteLLM key generation
    respx_mock.post("http://mock-litellm/key/generate").mock(
        return_value=httpx.Response(200, json={"key": "new-api-key"})
    )
    return respx_mock

@pytest.mark.asyncio
async def test_register_tenant_success(asgi_client, mock_httpx_responses, monkeypatch):
    response = await asgi_client.post(
        "/admin/onboarding/register",
        headers={"X-Admin-Key": "mock-admin-key"},
        json={"tenant_id": "test-tenant", "email": "test@example.com"}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["tenant_id"] == "test-tenant"
    assert response.json()["api_key"] == "new-api-key"
    assert response.json()["team_id"] == "new-tenant-id"

@pytest.mark.asyncio
async def test_register_tenant_unauthorized(asgi_client, mock_httpx_responses):
    response = await asgi_client.post(
        "/admin/onboarding/register",
        headers={"X-Admin-Key": "wrong-key"},
        json={"tenant_id": "test-tenant", "email": "test@example.com"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "unauthorized"

@pytest.mark.asyncio
async def test_register_tenant_litellm_failure(asgi_client, mock_httpx_responses, monkeypatch):
    mock_httpx_responses.post("http://mock-litellm/team/new").mock(
        return_value=httpx.Response(500, text="Internal LiteLLM Error")
    )
    response = await asgi_client.post(
        "/admin/onboarding/register",
        headers={"X-Admin-Key": "mock-admin-key"},
        json={"tenant_id": "test-tenant", "email": "test@example.com"}
    )
    assert response.status_code == 500
    assert response.json()["success"] is False
    assert "Failed to create team" in response.json()["error"]
