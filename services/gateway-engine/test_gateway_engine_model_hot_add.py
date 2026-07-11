"""Unit tests for gateway-engine runtime model hot add/delete routes."""

from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import main as t
from core.model_registry import ModelRegistryRecord, RegistryLoadResult


class _FakeRegistryStore:
    enabled = True

    def __init__(self):
        self.models: dict[str, ModelRegistryRecord] = {}

    def list_models(self):
        return RegistryLoadResult(
            source="postgres:model_registry",
            registry_available=True,
            models=list(self.models.values()),
        )

    def get_model(self, model_id: str):
        return self.models.get(model_id)

    def upsert_model(self, model: ModelRegistryRecord):
        self.models[model.model_id] = model
        return model

    def hard_delete_model(self, model_id: str):
        return self.models.pop(model_id, None) is not None


class _FakeRuntimeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"ok": True}
        self.text = ""

    def json(self):
        return self._payload


class _FakeRuntimeClient:
    def __init__(self, response=None, exc: Exception | None = None):
        self.response = response or _FakeRuntimeResponse()
        self.exc = exc
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.exc is not None:
            raise self.exc
        return self.response


def test_model_new_requires_admin_key(monkeypatch):
    monkeypatch.delenv("GATEWAY_ENGINE_ADMIN_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)

    client = TestClient(t.app)
    resp = client.post(
        "/model/new",
        json={"model_id": "gpt-5-4", "upstream_model": "gpt-5.4"},
    )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "admin_key_required"


def test_model_new_hot_add_upserts_registry_and_calls_litellm(monkeypatch):
    store = _FakeRegistryStore()
    fake_client = _FakeRuntimeClient(response=_FakeRuntimeResponse(status_code=200, payload={"created": True}))
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "LITELLM", "http://litellm:4000")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "litellm-master")

    client = TestClient(t.app)
    resp = client.post(
        "/model/new",
        headers={"x-admin-key": "test-admin"},
        json={
            "model_id": "gpt-5-4",
            "upstream_model": "gpt-5.4",
            "supports_tools": True,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["partial_success"] is False
    assert body["model"]["model_id"] == "gpt-5-4"
    assert "gpt-5-4" in store.models
    assert fake_client.calls[0]["url"] == "http://litellm:4000/model/new"
    assert fake_client.calls[0]["headers"]["authorization"] == "Bearer litellm-master"
    assert fake_client.calls[0]["json"]["model_name"] == "gpt-5-4"


def test_model_new_litellm_unreachable_returns_partial_success(monkeypatch):
    store = _FakeRegistryStore()
    fake_client = _FakeRuntimeClient(exc=RuntimeError("litellm down"))
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "LITELLM", "http://litellm:4000")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "litellm-master")

    client = TestClient(t.app)
    resp = client.post(
        "/model/new",
        headers={"x-admin-key": "test-admin"},
        json={"model_id": "gpt-5-4", "upstream_model": "gpt-5.4"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["partial_success"] is True
    assert body["litellm_add"]["ok"] is False
    assert "RuntimeError" in body["litellm_add"]["reason"]
    assert body["errors"][0]["code"] == "litellm_runtime_add_failed"
    assert "gpt-5-4" in store.models


def test_model_delete_hot_remove_updates_registry_and_calls_litellm(monkeypatch):
    store = _FakeRegistryStore()
    store.upsert_model(
        ModelRegistryRecord(
            model_id="gpt-5-4",
            provider="openai",
            family="openai",
            upstream_model="gpt-5.4",
            litellm_model="openai/gpt-5.4",
            enabled=True,
            status="UNKNOWN",
        )
    )
    fake_client = _FakeRuntimeClient(response=_FakeRuntimeResponse(status_code=200, payload={"deleted": True}))
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "LITELLM", "http://litellm:4000")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "litellm-master")

    client = TestClient(t.app)
    resp = client.post(
        "/model/delete",
        headers={"x-admin-key": "test-admin"},
        json={"model_id": "gpt-5-4"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["partial_success"] is False
    assert body["litellm_delete"]["ok"] is True
    assert body["model"]["model_id"] == "gpt-5-4"
    assert "gpt-5-4" not in store.models
    assert fake_client.calls[0]["url"] == "http://litellm:4000/model/delete"
