import json

import httpx
from fastapi.testclient import TestClient
from main import app


def test_responses_compact_interception():
    client = TestClient(app)

    import main

    class MockResponse:
        status_code = 200
        content = b'{"id": "resp_123", "object": "response.compaction", "output": []}'
        headers = {"content-type": "application/json"}

        def json(self):
            return json.loads(self.content.decode())

    called_body = None

    async def mock_request(method, url, headers=None, content=None, params=None):
        nonlocal called_body
        called_body = content
        return MockResponse()

    # Initialize main._client first
    main._client = httpx.AsyncClient()
    main._client.request = mock_request

    try:
        # 1. Test compaction for an OpenAI model (should not be mapped)
        response = client.post(
            "/v1/responses/compact",
            headers={"Authorization": "Bearer sk-test"},
            json={"model": "gpt-5-5", "input": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200
        body_data = json.loads(called_body.decode())
        assert body_data["model"] == "gpt-5-5"

        # 2. Test compaction for a non-OpenAI model (should be mapped to gpt-5-5)
        response = client.post(
            "/v1/responses/compact",
            headers={"Authorization": "Bearer sk-test"},
            json={"model": "claude-sonnet-4-6", "input": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 200
        body_data = json.loads(called_body.decode())
        assert body_data["model"] == "gpt-5-5"

    finally:
        main._client = None
