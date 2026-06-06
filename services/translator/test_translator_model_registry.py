"""Unit tests for translator-owned model registry admin APIs."""

from __future__ import annotations

import json
import os
import sys

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import main as t
from core.model_registry import (
    ModelRegistryRecord,
    RegistryLoadResult,
    build_reconcile_resources,
    load_models_from_litellm_config,
)


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

    def upsert_models(self, models: list[ModelRegistryRecord]):
        for model in models:
            self.models[model.model_id] = model
        return len(models)

    def update_probe_result(
        self,
        model_id: str,
        *,
        probe_status: str,
        probe_http_status: int | None,
        probe_checked_at,
    ):
        model = self.models.get(model_id)
        if model is None:
            return None
        updated = model.model_copy(
            update={
                "probe_status": probe_status,
                "probe_http_status": probe_http_status,
                "probe_checked_at": probe_checked_at,
            }
        )
        self.models[model_id] = updated
        return updated

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


class _FakeProbeClient:
    def __init__(self, response=None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.exc is not None:
            raise self.exc
        return self.response


class _FakeModelsClient:
    def __init__(self, response=None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.exc is not None:
            raise self.exc
        return self.response


class _FakeModelsResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {
            "data": [
                {"id": "gpt-5.4", "owned_by": "openai"},
                {"id": "AI-Gateway:claude-sonnet-4.6", "owned_by": "anthropic"},
            ]
        }

    def json(self):
        return self._payload


def _registry_model(model_id: str = "gpt-5-4") -> ModelRegistryRecord:
    return ModelRegistryRecord(
        model_id=model_id,
        provider="openai",
        family="openai",
        upstream_model="gpt-5.4",
        litellm_model="openai/gpt-5.4",
        enabled=True,
        status="UNKNOWN",
    )


def _gemini_registry_model() -> ModelRegistryRecord:
    return ModelRegistryRecord(
        model_id="gemini-3-flash",
        provider="gemini",
        family="gemini",
        upstream_model="gemini-3.flash",
        litellm_model="openai/gemini-3.flash",
        enabled=True,
        status="HEALTHY",
        supports_tools=True,
        supports_vision=True,
        max_input_tokens=1048576,
        policy_metadata={
            "api_base": "http://cliproxy:8317/v1",
            "fallbacks": ["gpt-5-4"],
        },
        aliases=[
            {
                "alias": "gemini-3.flash-preview",
                "target": "gemini-3-flash",
                "alias_kind": "compat",
            }
        ],
    )


def test_reconcile_renderer_outputs_valid_yaml_json_and_diffs():
    resources = build_reconcile_resources([_registry_model(), _gemini_registry_model()])
    by_name = {resource.name: resource for resource in resources}

    litellm = yaml.safe_load(by_name["litellm-config.yaml"].content)
    gemini_map = json.loads(by_name["gemini-model-map.json"].content)

    assert [entry["model_name"] for entry in litellm["model_list"]] == [
        "gemini-3-flash",
        "gpt-5-4",
    ]
    assert litellm["model_list"][0]["model_info"]["supports_vision"] is True
    assert litellm["litellm_settings"]["fallbacks"] == [{"gemini-3-flash": ["gpt-5-4"]}]
    assert gemini_map == {
        "gemini-3.flash": "gemini-3-flash",
        "gemini-3.flash-preview": "gemini-3-flash",
    }
    assert by_name["litellm-config.yaml"].changed is True
    assert "--- current/litellm-config.yaml" in by_name["litellm-config.yaml"].diff


def test_reconcile_renderer_marks_unchanged_when_current_matches():
    first = build_reconcile_resources([_registry_model(), _gemini_registry_model()])
    by_name = {resource.name: resource for resource in first}

    second = build_reconcile_resources(
        [_registry_model(), _gemini_registry_model()],
        current_litellm_config=by_name["litellm-config.yaml"].content,
        current_gemini_map=by_name["gemini-model-map.json"].content,
    )

    assert all(resource.changed is False for resource in second)
    assert all(resource.diff == "" for resource in second)


def test_load_models_from_litellm_config(tmp_path):
    config = tmp_path / "litellm-config.yaml"
    _write_config(config)

    result = load_models_from_litellm_config(str(config))

    assert result.source == "litellm-config"
    assert len(result.models) == 2
    sonnet = next(model for model in result.models if model.model_id == "claude-sonnet-4-6")
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


def test_admin_models_reconcile_requires_admin_key(monkeypatch):
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "")
    monkeypatch.delenv("TRANSLATOR_ADMIN_KEY", raising=False)

    client = TestClient(t.app)
    resp = client.post("/admin/models/reconcile", json={"dry_run": True})

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "admin_key_required"


def test_admin_models_reconcile_dry_run_does_not_write_files(monkeypatch, tmp_path):
    store = _FakeRegistryStore()
    store.models["gpt-5-4"] = _registry_model()
    store.models["gemini-3-flash"] = _gemini_registry_model()
    litellm_config = tmp_path / "litellm-config.yaml"
    gemini_map = tmp_path / "gemini-model-map.json"
    litellm_config.write_text("model_list: []\n", encoding="utf-8")
    gemini_map.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")
    monkeypatch.setattr(t, "LITELLM_CONFIG_PATH", str(litellm_config))
    monkeypatch.setattr(t, "GEMINI_MODEL_MAP_PATH", str(gemini_map))

    client = TestClient(t.app)
    resp = client.post(
        "/admin/models/reconcile",
        headers={"x-admin-key": "test-admin"},
        json={},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["source"] == "postgres:model_registry"
    assert [resource["name"] for resource in body["resources"]] == [
        "litellm-config.yaml",
        "gemini-model-map.json",
    ]
    assert all(resource["changed"] is True for resource in body["resources"])
    assert yaml.safe_load(body["resources"][0]["content"])["model_list"][0]["model_name"] == "gemini-3-flash"
    assert json.loads(body["resources"][1]["content"])["gemini-3.flash"] == "gemini-3-flash"
    assert litellm_config.read_text(encoding="utf-8") == "model_list: []\n"
    assert gemini_map.read_text(encoding="utf-8") == "{}\n"


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


def test_admin_models_sync_cliproxy_dry_run_normalizes_and_diffs(monkeypatch):
    store = _FakeRegistryStore()
    store.models["gpt-5-4"] = ModelRegistryRecord(
        model_id="gpt-5-4",
        provider="openai",
        family="openai",
        upstream_model="gpt-5.3",
        litellm_model="openai/gpt-5.3",
        enabled=True,
        status="HEALTHY",
        policy_metadata={"manual_note": "keep"},
        source="manual",
    )
    fake_client = _FakeModelsClient(response=_FakeModelsResponse())
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("CLIPROXY_API_KEY", "cliproxy-key")
    monkeypatch.setattr(t, "CLIPROXY_URL", "http://cliproxy:8317")

    client = TestClient(t.app)
    resp = client.post(
        "/admin/models/sync",
        headers={"x-admin-key": "test-admin"},
        json={"source": "cliproxy", "dry_run": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "cliproxy"
    assert body["imported_count"] == 2
    assert [model["model_id"] for model in body["models"]] == [
        "gpt-5-4",
        "claude-sonnet-4-6",
    ]
    assert {"kind": "add", "model_id": "claude-sonnet-4-6"} in body["diffs"]
    assert any(diff["kind"] == "update" and diff["model_id"] == "gpt-5-4" for diff in body["diffs"])
    assert body["models"][0]["policy_metadata"]["manual_note"] == "keep"
    assert fake_client.calls[0]["headers"] == {"authorization": "Bearer cliproxy-key"}
    assert store.models["gpt-5-4"].upstream_model == "gpt-5.3"


def test_admin_models_sync_cliproxy_apply_upserts(monkeypatch):
    store = _FakeRegistryStore()
    fake_client = _FakeModelsClient(response=_FakeModelsResponse())
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("CLIPROXY_API_KEY", "cliproxy-key")

    client = TestClient(t.app)
    resp = client.post(
        "/admin/models/sync",
        headers={"x-admin-key": "test-admin"},
        json={"source": "cliproxy", "dry_run": False},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported_count"] == 2
    assert store.models["gpt-5-4"].source == "cliproxy"
    assert store.models["claude-sonnet-4-6"].upstream_model == "claude-sonnet-4.6"


def test_admin_models_sync_cliproxy_error_does_not_write(monkeypatch):
    store = _FakeRegistryStore()
    fake_client = _FakeModelsClient(response=_FakeModelsResponse(status_code=502))
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("CLIPROXY_API_KEY", "cliproxy-key")

    client = TestClient(t.app)
    resp = client.post(
        "/admin/models/sync",
        headers={"x-admin-key": "test-admin"},
        json={"source": "cliproxy", "dry_run": False},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["imported_count"] == 0
    assert body["errors"][0]["code"] == "cliproxy_http_error"
    assert store.models == {}


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

    delete = client.delete("/admin/models/gpt-5-4", headers={"x-admin-key": "test-admin"})
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


def test_admin_model_probe_requires_admin_key(monkeypatch):
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "")
    monkeypatch.delenv("TRANSLATOR_ADMIN_KEY", raising=False)

    client = TestClient(t.app)
    resp = client.post("/admin/models/gpt-5-4/probe")

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "admin_key_required"


@pytest.mark.parametrize(
    ("response", "expected_status", "expected_http_status"),
    [
        (
            httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            ),
            "success",
            200,
        ),
        (httpx.Response(401, json={"error": {"message": "bad key"}}), "auth_failure", 401),
        (httpx.Response(403, json={"error": {"message": "bad key"}}), "auth_failure", 403),
        (httpx.Response(404, json={"error": {"message": "missing"}}), "missing_model", 404),
        (httpx.Response(429, json={"error": {"message": "rate limit"}}), "rate_limited", 429),
        (
            httpx.Response(503, json={"error": {"message": "unavailable"}}),
            "temporarily_unavailable",
            503,
        ),
        (httpx.Response(500, json={"error": {"message": "boom"}}), "temporarily_unavailable", 500),
        (httpx.Response(418, json={"error": {"message": "teapot"}}), "error", 418),
        (httpx.Response(200, json={"unexpected": []}), "malformed_response", 200),
    ],
)
def test_admin_model_probe_classifies_and_persists(monkeypatch, response, expected_status, expected_http_status):
    store = _FakeRegistryStore()
    store.models["gpt-5-4"] = _registry_model()
    fake_client = _FakeProbeClient(response=response)
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "litellm-key")

    client = TestClient(t.app)
    resp = client.post("/admin/models/gpt-5-4/probe", headers={"x-admin-key": "test-admin"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["probe_status"] == expected_status
    assert body["probe_http_status"] == expected_http_status
    assert body["model"]["probe_status"] == expected_status
    assert store.models["gpt-5-4"].probe_status == expected_status
    assert store.models["gpt-5-4"].probe_http_status == expected_http_status
    assert store.models["gpt-5-4"].enabled is True
    assert "chat/completions" in fake_client.calls[0]["url"]
    assert fake_client.calls[0]["json"]["model"] == "gpt-5-4"
    assert fake_client.calls[0]["json"]["max_tokens"] == 1
    assert fake_client.calls[0]["headers"]["authorization"] == "Bearer litellm-key"


def test_admin_model_probe_timeout_persists_without_disabling(monkeypatch):
    store = _FakeRegistryStore()
    store.models["gpt-5-4"] = _registry_model()
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "_client", _FakeProbeClient(exc=httpx.TimeoutException("slow")))
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")

    client = TestClient(t.app)
    resp = client.post("/admin/models/gpt-5-4/probe", headers={"x-admin-key": "test-admin"})

    assert resp.status_code == 200
    assert resp.json()["probe_status"] == "timeout"
    assert store.models["gpt-5-4"].probe_status == "timeout"
    assert store.models["gpt-5-4"].enabled is True
    assert store.models["gpt-5-4"].status == "UNKNOWN"


def test_regression_quota_cooldown_429_keeps_model_in_catalog(monkeypatch):
    """Registry probe must not disable models on provider quota cooldown (429)."""
    store = _FakeRegistryStore()
    store.models["gemini-3-flash"] = _registry_model(model_id="gemini-3-flash")
    fake_client = _FakeProbeClient(response=httpx.Response(429, json={"error": {"message": "quota cooldown"}}))
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "litellm-key")

    client = TestClient(t.app)
    resp = client.post("/admin/models/gemini-3-flash/probe", headers={"x-admin-key": "test-admin"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["probe_status"] == "rate_limited"
    assert body["probe_http_status"] == 429
    model = store.models["gemini-3-flash"]
    assert model.enabled is True
    assert model.status != "DISABLED"
    assert model.status != "UNAVAILABLE"


def test_admin_model_probe_missing_model_returns_404(monkeypatch):
    store = _FakeRegistryStore()
    monkeypatch.setattr(t, "_model_registry_store", lambda: store)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")

    client = TestClient(t.app)
    resp = client.post("/admin/models/missing/probe", headers={"x-admin-key": "test-admin"})

    assert resp.status_code == 404
    assert resp.json()["probe_status"] == "missing_model"
    assert resp.json()["errors"][0]["code"] == "model_not_found"
