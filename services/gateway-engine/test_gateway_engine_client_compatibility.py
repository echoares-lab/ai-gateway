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
