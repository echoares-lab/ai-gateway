"""Gate B coverage for the guarded unified configuration snapshot API."""

from __future__ import annotations

from types import SimpleNamespace

import main as gateway_engine_main
import pytest

pytestmark = pytest.mark.mock

_SECRET = "fixture-oauth-secret-must-not-leak"


def _headers(key: str = "admin-secret", scope: str = "config:read") -> dict[str, str]:
    return {"x-admin-key": key, "x-management-scope": scope}


def _registry_store(*model_ids: str):
    models = [SimpleNamespace(model_id=model_id) for model_id in model_ids]

    class Store:
        def list_models(self):
            return SimpleNamespace(registry_available=True, models=models, errors=[])

    return Store()


def _write_config(tmp_path):
    path = tmp_path / "deployed-litellm.yaml"
    path.write_text(
        """
model_list:
  - model_name: gpt-safe
    litellm_params:
      model: openai/gpt-safe
      api_key: os.environ/OPENAI_API_KEY
router_settings:
  routing_strategy: simple-shuffle
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _admin_environment(monkeypatch):
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    monkeypatch.setenv("OPENAI_API_KEY", _SECRET)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("GATEWAY_ENGINE_UNIFIED_CONFIG_ADMIN_API_ENABLED", raising=False)


@pytest.mark.asyncio
async def test_disabled_default_reads_no_sources_or_providers(monkeypatch, asgi_client, tmp_path):
    calls: list[str] = []
    monkeypatch.delenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", raising=False)
    monkeypatch.setattr(gateway_engine_main, "LITELLM_CONFIG_PATH", str(tmp_path / "must-not-be-read.yaml"))
    monkeypatch.setattr(
        gateway_engine_main,
        "_model_registry_store",
        lambda: calls.append("registry") or _registry_store("gpt-safe"),
    )

    async def runtime():
        calls.append("runtime")
        return (["gpt-safe"], [])

    monkeypatch.setattr(gateway_engine_main, "_admin_fetch_visible_models", runtime)
    response = await asgi_client.get("/admin/config", headers=_headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "config_snapshot_disabled"
    assert response.headers["cache-control"] == "no-store"
    assert calls == []


@pytest.mark.asyncio
async def test_enabled_authentication_matrix_reads_no_sources(monkeypatch, asgi_client, tmp_path):
    calls: list[str] = []
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setattr(gateway_engine_main, "LITELLM_CONFIG_PATH", str(tmp_path / "must-not-be-read.yaml"))
    monkeypatch.setattr(
        gateway_engine_main,
        "_model_registry_store",
        lambda: calls.append("registry") or _registry_store("gpt-safe"),
    )
    responses = [
        await asgi_client.get("/admin/config", headers={"x-management-scope": "config:read"}),
        await asgi_client.get("/admin/config", headers=_headers(key="wrong")),
        await asgi_client.get("/admin/config", headers=_headers(scope="config:generate")),
    ]
    assert [response.status_code for response in responses] == [401, 401, 403]
    assert [response.json()["error"]["code"] for response in responses] == [
        "config_snapshot_auth_required",
        "config_snapshot_auth_required",
        "config_snapshot_scope_forbidden",
    ]
    assert all(response.headers["cache-control"] == "no-store" for response in responses)
    assert calls == []


@pytest.mark.asyncio
async def test_healthy_fixed_sources_return_safe_snapshot(
    monkeypatch,
    asgi_client,
    mock_litellm_router,
    tmp_path,
):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setattr(gateway_engine_main, "LITELLM_CONFIG_PATH", str(_write_config(tmp_path)))
    monkeypatch.setattr(gateway_engine_main, "_model_registry_store", lambda: _registry_store("gpt-safe"))

    async def runtime():
        return ["gpt-safe"], []

    monkeypatch.setattr(gateway_engine_main, "_admin_fetch_visible_models", runtime)
    response = await asgi_client.get("/admin/config", headers=_headers())
    assert response.status_code == 200
    assert response.json()["schema"] == "config-snapshot.v1"
    assert response.json()["status"] == "ok"
    assert response.json()["models"]["configured"] == ["gpt-safe"]
    assert response.headers["cache-control"] == "no-store"
    assert _SECRET not in response.text
    assert len(mock_litellm_router.calls) == 0


@pytest.mark.asyncio
async def test_runtime_failure_returns_degraded_without_provider_oauth(
    monkeypatch,
    asgi_client,
    mock_litellm_router,
    tmp_path,
):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setattr(gateway_engine_main, "LITELLM_CONFIG_PATH", str(_write_config(tmp_path)))
    monkeypatch.setattr(gateway_engine_main, "_model_registry_store", lambda: _registry_store("gpt-safe"))

    async def unavailable_runtime():
        return None, [{"code": "models_fetch_error", "message": _SECRET, "location": "oauth/provider"}]

    monkeypatch.setattr(gateway_engine_main, "_admin_fetch_visible_models", unavailable_runtime)
    response = await asgi_client.get("/admin/config", headers=_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["drift"]["status"] == "unknown"
    assert {"source": "runtime-visible-models", "code": "source_unavailable"} in response.json()["errors"]
    assert _SECRET not in response.text
    assert len(mock_litellm_router.calls) == 0


@pytest.mark.asyncio
async def test_dynamic_rollback_restores_disabled_zero_read_state(monkeypatch, asgi_client, tmp_path):
    calls: list[str] = []
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setattr(gateway_engine_main, "LITELLM_CONFIG_PATH", str(_write_config(tmp_path)))
    monkeypatch.setattr(
        gateway_engine_main,
        "_model_registry_store",
        lambda: calls.append("registry") or _registry_store("gpt-safe"),
    )

    async def runtime():
        calls.append("runtime")
        return (["gpt-safe"], [])

    monkeypatch.setattr(gateway_engine_main, "_admin_fetch_visible_models", runtime)
    assert (await asgi_client.get("/admin/config", headers=_headers())).status_code == 200
    calls.clear()
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "false")
    response = await asgi_client.get("/admin/config", headers=_headers())
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert calls == []
