"""Unit tests for the C-SVC-2 config generation adapter."""

import json

import api.config_generation as generation
import pytest
from fastapi.testclient import TestClient
from main import app


def _headers(scope="config:generate"):
    return {"x-admin-key": "admin-secret", "x-management-scope": scope}


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("CONFIG_GENERATION_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    monkeypatch.delenv("CONFIG_GENERATION_DEFAULT_BASE_URL", raising=False)
    generation._IDEMPOTENCY_CACHE.clear()


def test_disabled_by_default_is_a_safe_rollback(monkeypatch):
    monkeypatch.delenv("CONFIG_GENERATION_API_ENABLED", raising=False)
    monkeypatch.delenv("GATEWAY_ENGINE_CONFIG_GENERATION_API_ENABLED", raising=False)
    response = TestClient(app).post("/v1/config/generate", json={"client": "cursor"})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "config_generation_disabled", "message": "Configuration generation is disabled"}
    }


def test_authentication_and_scope_are_required(enabled):
    client = TestClient(app)
    missing = client.post("/v1/config/generate", json={"client": "cursor"})
    assert missing.status_code == 401
    wrong_scope = client.post("/v1/config/generate", headers=_headers("config:read"), json={"client": "cursor"})
    assert wrong_scope.status_code == 403


def test_single_profile_is_deterministic_and_placeholder_only(enabled):
    client = TestClient(app)
    request = {"client": "codex", "base_url": "https://gateway.example/v1/", "org": "acme"}
    first = client.post("/v1/config/generate", headers=_headers(), json=request)
    second = client.post("/v1/config/generate", headers=_headers(), json=request)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    body = first.json()
    assert body["schema_version"] == "client-config.v1"
    assert body["base_url"] == "https://gateway.example"
    assert body["tenant_key_example"] == "ak-acme-core-eng-my-repo-dev"
    assert "${AI_GATEWAY_KEY}" in body["config"]
    assert "gateway.example/v1" in body["config"]
    assert "admin-secret" not in first.text
    assert "/root/" not in first.text


def test_all_profiles_have_stable_order_and_service_default_precedence(monkeypatch, enabled):
    monkeypatch.setenv("CONFIG_GENERATION_DEFAULT_BASE_URL", "https://configured.example/v1")
    client = TestClient(app)
    response = client.post("/v1/config/generate", headers=_headers(), json={"client": "all"})
    assert response.status_code == 200
    body = response.json()
    assert list(body["profiles"]) == ["cursor", "claude-code", "codex", "gemini", "openai-sdk"]
    assert body["base_url"] == "https://configured.example"
    assert all("${AI_GATEWAY_KEY}" in text for text in body["profiles"].values())
    # Explicit request values override service defaults.
    override = client.post(
        "/v1/config/generate",
        headers=_headers(),
        json={"client": "cursor", "base_url": "http://request.example"},
    )
    assert override.json()["base_url"] == "http://request.example"


@pytest.mark.parametrize(
    "payload",
    [
        {"client": "unknown"},
        {"client": "cursor", "key_var": "${SECRET}"},
        {"client": "cursor", "repo": "../../etc"},
        {"client": "cursor", "base_url": "https://user:password@gateway.example"},
        {"client": "cursor", "base_url": "https://gateway.example?token=secret"},
        {"client": "cursor", "unexpected": "field"},
    ],
)
def test_invalid_inputs_use_stable_error(enabled, payload):
    response = TestClient(app).post("/v1/config/generate", headers=_headers(), json=payload)
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_request", "message": "Configuration request is invalid"}}


def test_request_and_response_limits(enabled):
    client = TestClient(app)
    too_large = client.post(
        "/v1/config/generate",
        headers=_headers(),
        content=json.dumps({"client": "cursor", "org": "a" * 64}) + (" " * generation._MAX_REQUEST_BYTES),
    )
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "request_too_large"


def test_idempotency_replays_same_request_and_rejects_different_request(enabled):
    client = TestClient(app)
    headers = {**_headers(), "idempotency-key": "config-retry-1"}
    first = client.post("/v1/config/generate", headers=headers, json={"client": "gemini"})
    replay = client.post("/v1/config/generate", headers=headers, json={"client": "gemini"})
    conflict = client.post("/v1/config/generate", headers=headers, json={"client": "cursor"})
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"
