"""Unit tests for translator-owned model registry admin APIs."""

from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import main as t
from core.model_registry import ModelRegistryRecord, load_models_from_litellm_config


class _FakeRegistryStore:
    enabled = True

    def __init__(self):
        self.models: dict[str, ModelRegistryRecord] = {}

    def list_models(self):
        raise AssertionError("not used")

    def get_model(self, model_id: str):
        return self.models.get(model_id)

    def upsert_model(self, model: ModelRegistryRecord):
        self.models[model.model_id] = model
        return model

    def disable_model(self, model_id: str):
        model = self.models.get(model_id)
        if model is None:
            return None
        disabled = model.model_copy(update={"enabled": False, "status": "DISABLED"})
        self.models[model_id] = disabled
        return disabled

    def hard_delete_model(self, model_id: str):
        return self.models.pop(model_id, None) is not None


def _write_config(path):
    path.write_text(
        """
model_list:
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: openai/claude-sonnet-4.6
      api_base: http://cliproxy:8317/v1
      api_key: os.environ/CLIPROXY_API_KEY
    model_info:
      supports_function_calling: true
      supports_vision: false
      max_input_tokens: 200000
  - model_name: gemini-3-flash
    litellm_params:
      model: openai/gemini-3.flash
      api_base: http://cliproxy:8317/v1
      api_key: os.environ/CLIPROXY_API_KEY
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
""",
        encoding="utf-8",
    )


def test_load_models_from_litellm_config(tmp_path):
    config = tmp_path / "litellm-config.yaml"
    _write_config(config)

    result = load_models_from_litellm_config(str(config))

    assert result.source == "litellm-config"
    assert len(result.models) == 2
    sonnet = next(
        model for model in result.models if model.model_id == "claude-sonnet-4-6"
    )
    assert sonnet.provider == "anthropic"
    assert sonnet.upstream_model == "claude-sonnet-4.6"
    assert sonnet.supports_tools is True
    assert sonnet.max_input_tokens == 200000


def test_admin_models_falls_back_to_litellm_config(monkeypatch, tmp_path):
    config = tmp_path / "litellm-config.yaml"
    _write_config(config)
    monkeypatch.setattr(t, "LITELLM_CONFIG_PATH", str(config))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MODEL_REGISTRY_DATABASE_URL", raising=False)

    client = TestClient(t.app)
    resp = client.get("/admin/models")

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "litellm-config:fallback"
    assert body["registry_available"] is False
    assert [model["model_id"] for model in body["models"]] == [
        "claude-sonnet-4-6",
        "gemini-3-flash",
    ]


def test_admin_model_returns_404_for_missing_model(monkeypatch, tmp_path):
    config = tmp_path / "litellm-config.yaml"
    _write_config(config)
    monkeypatch.setattr(t, "LITELLM_CONFIG_PATH", str(config))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MODEL_REGISTRY_DATABASE_URL", raising=False)

    client = TestClient(t.app)
    resp = client.get("/admin/models/not-a-model")

    assert resp.status_code == 404
    assert resp.json()["models"] == []


def test_admin_models_sync_requires_admin_key(monkeypatch, tmp_path):
    config = tmp_path / "litellm-config.yaml"
    _write_config(config)
    monkeypatch.setattr(t, "LITELLM_CONFIG_PATH", str(config))
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "")
    monkeypatch.delenv("TRANSLATOR_ADMIN_KEY", raising=False)

    client = TestClient(t.app)
    resp = client.post("/admin/models/sync", json={"dry_run": True})

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "admin_key_required"


def test_admin_models_sync_dry_run(monkeypatch, tmp_path):
    config = tmp_path / "litellm-config.yaml"
    _write_config(config)
    monkeypatch.setattr(t, "LITELLM_CONFIG_PATH", str(config))
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")

    client = TestClient(t.app)
    resp = client.post(
        "/admin/models/sync",
        headers={"x-admin-key": "test-admin"},
        json={"dry_run": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["imported_count"] == 2
    assert body["models"][0]["source"] == "litellm-config"


def test_admin_model_create_patch_and_disable(monkeypatch):
    store = _FakeRegistryStore()
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")

    client = TestClient(t.app)
    create = client.post(
        "/admin/models",
        headers={"x-admin-key": "test-admin"},
        json={
            "model_id": "gpt-5-4",
            "upstream_model": "gpt-5.4",
            "supports_tools": True,
        },
    )
    assert create.status_code == 200
    assert create.json()["model"]["litellm_model"] == "openai/gpt-5.4"
    assert store.models["gpt-5-4"].provider == "openai"

    patch = client.patch(
        "/admin/models/gpt-5-4",
        headers={"x-admin-key": "test-admin"},
        json={"status": "HEALTHY", "cost_tier": 2},
    )
    assert patch.status_code == 200
    assert patch.json()["model"]["status"] == "HEALTHY"
    assert patch.json()["model"]["cost_tier"] == 2

    delete = client.delete(
        "/admin/models/gpt-5-4", headers={"x-admin-key": "test-admin"}
    )
    assert delete.status_code == 200
    assert delete.json()["model"]["enabled"] is False
    assert delete.json()["model"]["status"] == "DISABLED"


def test_admin_model_patch_missing_returns_404(monkeypatch):
    store = _FakeRegistryStore()
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")

    client = TestClient(t.app)
    resp = client.patch(
        "/admin/models/missing",
        headers={"x-admin-key": "test-admin"},
        json={"enabled": False},
    )

    assert resp.status_code == 404
    assert resp.json()["errors"][0]["code"] == "model_not_found"
