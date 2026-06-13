from unittest.mock import patch

import httpx
import main as t
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(t, "ENABLE_VIRTUAL_PROVIDERS", True)
    return TestClient(t.app)


def test_virtual_provider_echoes_prompt(client, monkeypatch):
    # Simulate an incoming Claude message
    body = {"model": "virt-claude-test", "messages": [{"role": "user", "content": "Hello Virtual World!"}]}

    # We hit the Claude proxy endpoint
    resp = client.post("/v1/messages", json=body)
    assert resp.status_code == 200

    # Check the anthropic-style response format
    data = resp.json()
    assert data["type"] == "message"
    assert data["model"] == "virt-claude-test"
    assert len(data["content"]) == 1
    assert "Hello Virtual World!" in data["content"][0]["text"]
    assert "[Virtual Response]" in data["content"][0]["text"]


def test_virtual_provider_simulates_429(client):
    body = {"model": "virt-error-429", "messages": [{"role": "user", "content": "Trigger limit"}]}

    # We hit the raw chat completions endpoint
    resp = client.post("/v1/chat/completions", json=body)
    assert resp.status_code == 429
    data = resp.json()
    assert data["error"]["code"] == 429
    assert "Simulated virtual error 429" in data["error"]["message"]


def test_virtual_provider_disabled_by_default(monkeypatch):
    monkeypatch.setattr(t, "ENABLE_VIRTUAL_PROVIDERS", False)

    body = {"model": "virt-error-429", "messages": [{"role": "user", "content": "Trigger limit"}]}

    with TestClient(t.app) as client:
        with patch("httpx.AsyncClient.request") as mock_request:
            mock_request.return_value = httpx.Response(200, content=b'{"id":"real","choices":[]}')
            resp = client.post("/v1/chat/completions", json=body)
            assert resp.status_code == 200
            assert resp.json().get("id") == "real"
