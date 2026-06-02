import pytest
from fastapi.testclient import TestClient
from translator import app
import json
import httpx

def test_tenancy_metadata_extraction():
    client = TestClient(app)
    
    import translator
    
    class MockResponse:
        status_code = 200
        content = b'{"id": "resp_123", "choices": []}'
        headers = {"content-type": "application/json"}
        def json(self):
            return json.loads(self.content.decode())
    
    called_body = None
    
    async def mock_request(method, url, **kwargs):
        nonlocal called_body
        called_body = kwargs.get("content") or kwargs.get("data")
        return MockResponse()
        
    translator._client = httpx.AsyncClient()
    translator._client.request = mock_request
    
    tenant_key = "Bearer ak-echoares-core-eng-gateway-dev"
    
    try:
        # 1. Test catch-all openai proxy (/v1/chat/completions)
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": tenant_key},
            json={"model": "gpt-5-5", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert response.status_code == 200
        body_data = json.loads(called_body.decode())
        assert "metadata" in body_data
        assert body_data["metadata"]["tenant_id"] == "echoares"
        assert body_data["metadata"]["workspace_id"] == "core"
        assert body_data["metadata"]["team_id"] == "eng"
        assert body_data["metadata"]["repo_name"] == "gateway"
        assert body_data["metadata"]["environment"] == "dev"

        # 2. Test Claude proxy (/v1/messages)
        response = client.post(
            "/v1/messages",
            headers={"x-api-key": "ak-echoares-core-eng-gateway-dev"},
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert response.status_code == 200
        body_data = json.loads(called_body.decode())
        assert "metadata" in body_data
        assert body_data["metadata"]["tenant_id"] == "echoares"
        assert body_data["metadata"]["workspace_id"] == "core"
        assert body_data["metadata"]["team_id"] == "eng"
        assert body_data["metadata"]["repo_name"] == "gateway"
        assert body_data["metadata"]["environment"] == "dev"

        # 3. Test Codex proxy (/v1/responses)
        response = client.post(
            "/v1/responses",
            headers={"Authorization": tenant_key},
            json={"model": "gpt-5-5", "input": "hi"}
        )
        assert response.status_code == 200
        body_data = json.loads(called_body.decode())
        assert "metadata" in body_data
        assert body_data["metadata"]["tenant_id"] == "echoares"
        assert body_data["metadata"]["workspace_id"] == "core"
        assert body_data["metadata"]["team_id"] == "eng"
        assert body_data["metadata"]["repo_name"] == "gateway"
        assert body_data["metadata"]["environment"] == "dev"

        # 4. Test Gemini proxy (/v1beta/models/gemini-3-flash:generateContent)
        response = client.post(
            "/v1beta/models/gemini-3-flash:generateContent",
            headers={"Authorization": tenant_key},
            json={"contents": [{"parts": [{"text": "hi"}]}]}
        )
        assert response.status_code == 200
        body_data = json.loads(called_body.decode())
        assert "metadata" in body_data
        assert body_data["metadata"]["tenant_id"] == "echoares"
        assert body_data["metadata"]["workspace_id"] == "core"
        assert body_data["metadata"]["team_id"] == "eng"
        assert body_data["metadata"]["repo_name"] == "gateway"
        assert body_data["metadata"]["environment"] == "dev"

    finally:
        translator._client = None
