import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_cursor_client_profile_application():
    """Verify that Cursor user-agent triggers injection of client headers."""
    
    # Mock the upstream proxy request to LiteLLM
    with patch("main._client", new_callable=AsyncMock) as mock_client:
        # Create a real Mock object for the response
        # The engine uses await _client.request(request.method, url, ...)
        
        mock_response = MagicMock()
        
        # Configure status_code to 200
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": []}
        mock_response.content = b'{"choices": []}'
        mock_response.headers = {}
        
        # Configure _client.request to return the mock_response
        mock_client.request.return_value = mock_response
        
        # Simulate Cursor request
        response = client.post(
            "/v1/chat/completions",
            headers={
                "Authorization": "Bearer sk-test",
                "User-Agent": "Cursor/1.0.0"
            },
            json={"model": "gpt-4", "messages": []}
        )
        
        assert response.status_code == 200
        
        # Verify the header injection from cursor.yaml
        # Access the first argument of the request call (the method is arg 0, url arg 1, headers arg 2)
        called_args = mock_client.request.call_args
        sent_headers = called_args[1]["headers"]
        assert sent_headers["x-gateway-client"] == "cursor"
