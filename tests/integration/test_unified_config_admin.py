"""Gate B coverage for the guarded unified configuration snapshot API."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import main as gateway_engine_main
import pytest
import yaml
from api.unified_config_admin import _MAX_SOURCE_BYTES
from test_gateway_engine_unified_config_contract import PRODUCTION_SHAPED_INPUT

pytestmark = pytest.mark.mock

_SECRET = "fixture-oauth-secret-must-not-leak"


def _headers(key: str = "admin-secret", scope: str = "config:read") -> dict[str, str]:
    return {"x-admin-key": key, "x-management-scope": scope}


def _registry_store(*model_ids: str):
    models = [SimpleNamespace(model_id=model_id) for model_id in model_ids]

    class Store:
        def list_models(self):
            return SimpleNamespace(registry_available=True, models=models, errors=[])

        def list_models_for_snapshot(self):
            return self.list_models()

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


def _write_production_shaped_config(tmp_path):
    path = tmp_path / "production-shaped-litellm.yaml"
    path.write_text(PRODUCTION_SHAPED_INPUT["litellm_yaml"], encoding="utf-8")
    return path


def _assert_openapi_snapshot_shape(payload):
    document = yaml.safe_load(
        (Path(__file__).parents[2] / "docs" / "openapi" / "gateway-engine.yaml").read_text(encoding="utf-8")
    )
    schema = document["components"]["schemas"]["UnifiedConfigSnapshot"]
    assert set(payload) == set(schema["required"])
    assert payload["schema"] in schema["properties"]["schema"]["enum"]
    assert payload["status"] in schema["properties"]["status"]["enum"]
    source_schema = schema["properties"]["sources"]["items"]
    for source in payload["sources"]:
        assert set(source_schema["required"]) <= set(source) <= set(source_schema["properties"])
        assert source["status"] in source_schema["properties"]["status"]["enum"]
        assert ("digest" in source) is (source["status"] == "ok")
    transport_enum = schema["properties"]["mcp"]["items"]["properties"]["transport"]["enum"]
    assert all(server["transport"] in transport_enum for server in payload["mcp"])


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
async def test_production_shaped_fixture_matches_openapi_when_healthy_and_degraded(
    monkeypatch,
    asgi_client,
    mock_litellm_router,
    tmp_path,
):
    aliases = ("claude-sonnet-4-6", "gemini-3-flash")
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("CLIPROXY_API_KEY", _SECRET)
    monkeypatch.setattr(gateway_engine_main, "LITELLM_CONFIG_PATH", str(_write_production_shaped_config(tmp_path)))
    monkeypatch.setattr(gateway_engine_main, "_model_registry_store", lambda: _registry_store(*aliases))

    async def healthy_runtime():
        return list(aliases), []

    monkeypatch.setattr(gateway_engine_main, "_admin_fetch_visible_models", healthy_runtime)
    healthy = await asgi_client.get("/admin/config", headers=_headers())

    assert healthy.status_code == 200
    assert healthy.json()["status"] == "ok"
    assert healthy.json()["models"]["providers"] == [
        {"alias": "claude-sonnet-4-6", "family": "anthropic"},
        {"alias": "gemini-3-flash", "family": "gemini"},
    ]
    assert healthy.json()["models"]["fallbacks"] == [{"from": "claude-sonnet-4-6", "to": ["gemini-3-flash"]}]
    assert healthy.json()["mcp"] == [{"alias": "mcp-git", "transport": "stdio"}]
    _assert_openapi_snapshot_shape(healthy.json())

    async def unavailable_runtime():
        return None, [{"code": "models_fetch_error", "message": "private failure"}]

    monkeypatch.setattr(gateway_engine_main, "_admin_fetch_visible_models", unavailable_runtime)
    degraded = await asgi_client.get("/admin/config", headers=_headers())

    assert degraded.status_code == 200
    assert degraded.json()["status"] == "degraded"
    assert degraded.json()["drift"]["status"] == "unknown"
    _assert_openapi_snapshot_shape(degraded.json())
    assert "private" not in degraded.text
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
async def test_real_runtime_http_timeout_remains_typed_source_timeout(
    monkeypatch,
    asgi_client,
    tmp_path,
):
    class TimeoutClient:
        async def get(self, url, *, headers, timeout):
            assert timeout == 2.0
            raise httpx.ReadTimeout("private runtime URL timed out", request=httpx.Request("GET", url))

        async def aclose(self):
            return None

    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setattr(gateway_engine_main, "LITELLM_CONFIG_PATH", str(_write_config(tmp_path)))
    monkeypatch.setattr(gateway_engine_main, "_model_registry_store", lambda: _registry_store("gpt-safe"))
    monkeypatch.setattr(gateway_engine_main, "_client", TimeoutClient())

    response = await asgi_client.get("/admin/config", headers=_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["drift"]["status"] == "unknown"
    assert {"source": "runtime-visible-models", "code": "source_timeout"} in response.json()["errors"]
    assert "private runtime URL" not in response.text


@pytest.mark.asyncio
async def test_multibyte_fixed_source_is_rejected_by_byte_size_without_leaking_path(
    monkeypatch,
    asgi_client,
    mock_litellm_router,
    tmp_path,
):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    path = tmp_path / "private-multibyte-config.yaml"
    path.write_bytes("é".encode("utf-8") * ((_MAX_SOURCE_BYTES // 2) + 1))
    monkeypatch.setattr(gateway_engine_main, "LITELLM_CONFIG_PATH", str(path))
    monkeypatch.setattr(gateway_engine_main, "_model_registry_store", lambda: _registry_store("gpt-safe"))

    async def runtime():
        return ["gpt-safe"], []

    monkeypatch.setattr(gateway_engine_main, "_admin_fetch_visible_models", runtime)

    with pytest.raises(ValueError):
        gateway_engine_main._load_unified_config_litellm_text()
    response = await asgi_client.get("/admin/config", headers=_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert {"source": "litellm-config", "code": "source_invalid"} in response.json()["errors"]
    assert str(path) not in response.text
    assert "private-multibyte-config" not in response.text
    assert len(mock_litellm_router.calls) == 0


@pytest.mark.asyncio
async def test_invalid_utf8_fixed_source_is_safe_source_invalid(
    monkeypatch,
    asgi_client,
    mock_litellm_router,
    tmp_path,
):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    path = tmp_path / "private-invalid-utf8.yaml"
    path.write_bytes(b"\xffinvalid-secret-marker")
    monkeypatch.setattr(gateway_engine_main, "LITELLM_CONFIG_PATH", str(path))
    monkeypatch.setattr(gateway_engine_main, "_model_registry_store", lambda: _registry_store("gpt-safe"))
    open_modes: list[str] = []
    real_open = open

    def tracked_open(file, mode="r", *args, **kwargs):
        open_modes.append(mode)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(gateway_engine_main, "open", tracked_open, raising=False)

    async def runtime():
        return ["gpt-safe"], []

    monkeypatch.setattr(gateway_engine_main, "_admin_fetch_visible_models", runtime)
    response = await asgi_client.get("/admin/config", headers=_headers())

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert {"source": "litellm-config", "code": "source_invalid"} in response.json()["errors"]
    assert open_modes == ["rb"]
    assert "invalid-secret-marker" not in response.text
    assert str(path) not in response.text
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
