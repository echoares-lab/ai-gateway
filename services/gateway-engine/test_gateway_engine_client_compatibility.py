import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_cursor_client_profile_application():
    """Verify that Cursor user-agent triggers injection of client headers."""
    with patch("main._client", new_callable=AsyncMock) as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": []}
        mock_response.content = b'{"choices": []}'
        mock_response.headers = {}
        mock_client.request.return_value = mock_response

        response = client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": "Bearer sk-test",
                "User-Agent": "Cursor/1.0.0",
            },
            json={"model": "gpt-4", "messages": []},
        )

        assert response.status_code == 200
        sent_headers = mock_client.request.call_args[1]["headers"]
        assert sent_headers["x-gateway-client"] == "cursor"


@pytest.mark.asyncio
async def test_x_force_model_header(monkeypatch):
    """Verify that X-Force-Model header overrides target model name."""
    monkeypatch.setenv("ALLOW_DEV_MODEL_FORCE", "true")
    with patch("main._client", new_callable=AsyncMock) as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": []}
        mock_response.content = b'{"choices": []}'
        mock_response.headers = {}
        mock_client.request.return_value = mock_response

        response = client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": "Bearer sk-test",
                "X-Force-Model": "gemini-3-flash",
            },
            json={"model": "gpt-4", "messages": []},
        )

        assert response.status_code == 200
        sent_body = json.loads(mock_client.request.call_args[1]["content"])
        assert sent_body["model"] == "gemini-3-flash"


@pytest.mark.asyncio
async def test_force_model_override_env(monkeypatch):
    """Verify that FORCE_MODEL_OVERRIDE env var overrides target model name."""
    monkeypatch.setenv("FORCE_MODEL_OVERRIDE", "claude-sonnet-4-6")
    with patch("main._client", new_callable=AsyncMock) as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": []}
        mock_response.content = b'{"choices": []}'
        mock_response.headers = {}
        mock_client.request.return_value = mock_response

        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-test"},
            json={"model": "gpt-4", "messages": []},
        )

        assert response.status_code == 200
        sent_body = json.loads(mock_client.request.call_args[1]["content"])
        assert sent_body["model"] == "claude-sonnet-4-6"
