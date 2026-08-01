"""Unit tests for the guarded unified configuration snapshot endpoint."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import api.admin_panels as admin_panels
import api.unified_config_admin as unified
import httpx
import pytest
import yaml
from api.unified_config_admin import UnifiedConfigAdminDeps, configure_unified_config_admin
from fastapi import FastAPI
from fastapi.testclient import TestClient

HEALTHY_YAML = """
model_list:
  - model_name: gpt-safe
    litellm_params:
      model: openai/gpt-safe
      api_key: os.environ/OPENAI_API_KEY
router_settings:
  routing_strategy: simple-shuffle
  num_retries: 2
"""
GENERATED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _headers(scope: str = "config:read") -> dict[str, str]:
    return {"x-admin-key": "admin-secret", "x-management-scope": scope}


@dataclass
class SourceSpies:
    calls: list[str] = field(default_factory=list)

    def litellm(self) -> str:
        self.calls.append("litellm")
        return HEALTHY_YAML

    def registry(self) -> tuple[str, ...]:
        self.calls.append("registry")
        return ("gpt-safe",)

    async def runtime(self) -> tuple[str, ...]:
        self.calls.append("runtime")
        return ("AI-Gateway:gpt-safe",)

    def environment(self) -> dict[str, str]:
        self.calls.append("environment")
        return {"OPENAI_API_KEY": "fixture-secret-value"}

    def now(self) -> datetime:
        self.calls.append("now")
        return GENERATED_AT


def _client(
    spies: SourceSpies,
    *,
    load_litellm_text=None,
    load_registry_model_ids=None,
    fetch_runtime_model_ids=None,
    environment=None,
) -> TestClient:
    configure_unified_config_admin(
        UnifiedConfigAdminDeps(
            load_litellm_text=load_litellm_text or spies.litellm,
            load_registry_model_ids=load_registry_model_ids or spies.registry,
            fetch_runtime_model_ids=fetch_runtime_model_ids or spies.runtime,
            environment=environment or spies.environment,
            now=spies.now,
        )
    )
    app = FastAPI()
    app.include_router(unified.router)
    return TestClient(app)


@pytest.fixture
def source_spies() -> SourceSpies:
    return SourceSpies()


@pytest.fixture
def configured_client(monkeypatch, source_spies) -> TestClient:
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("GATEWAY_ENGINE_UNIFIED_CONFIG_ADMIN_API_ENABLED", raising=False)
    return _client(source_spies)


def _assert_no_store(response) -> None:
    assert response.headers["cache-control"] == "no-store"


def test_disabled_by_default_does_not_read_sources(monkeypatch, configured_client, source_spies):
    monkeypatch.delenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", raising=False)
    response = configured_client.get("/admin/config", headers=_headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "config_snapshot_disabled"
    assert source_spies.calls == []
    _assert_no_store(response)


def test_enabled_missing_server_auth_returns_503_before_source_reads(monkeypatch, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.delenv("GATEWAY_ENGINE_ADMIN_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    response = _client(source_spies).get("/admin/config", headers=_headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "config_snapshot_unavailable"
    assert source_spies.calls == []
    _assert_no_store(response)


def test_non_ascii_configured_key_returns_typed_503(monkeypatch, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admïn-secret")
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)

    response = _client(source_spies).get("/admin/config", headers=_headers())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "config_snapshot_unavailable"
    assert source_spies.calls == []
    _assert_no_store(response)


def test_non_ascii_supplied_key_returns_typed_401(monkeypatch, configured_client, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    headers = [
        (b"x-admin-key", b"adm\xffn-secret"),
        (b"x-management-scope", b"config:read"),
    ]

    response = configured_client.get("/admin/config", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "config_snapshot_auth_required"
    assert source_spies.calls == []
    _assert_no_store(response)


@pytest.mark.parametrize("key", [None, "wrong-key"])
def test_enabled_rejects_missing_or_wrong_key_before_source_reads(monkeypatch, configured_client, source_spies, key):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    headers = {"x-management-scope": "config:read"}
    if key is not None:
        headers["x-admin-key"] = key
    response = configured_client.get("/admin/config", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "config_snapshot_auth_required"
    assert source_spies.calls == []
    _assert_no_store(response)


def test_enabled_requires_exact_scope(monkeypatch, configured_client, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    response = configured_client.get("/admin/config", headers=_headers("config:generate"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "config_snapshot_scope_forbidden"
    assert source_spies.calls == []
    _assert_no_store(response)


def test_healthy_success_uses_only_safe_builder_projection(monkeypatch, configured_client, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    response = configured_client.get("/admin/config", headers=_headers())
    assert response.status_code == 200
    assert response.json()["schema"] == "config-snapshot.v1"
    assert response.json()["status"] == "ok"
    assert response.json()["models"]["configured"] == ["gpt-safe"]
    assert sorted(source_spies.calls[:3]) == ["litellm", "registry", "runtime"]
    assert source_spies.calls[3:] == ["environment", "now"]
    assert "fixture-secret-value" not in response.text
    assert "api_key" not in response.text
    _assert_no_store(response)


def test_query_parameters_are_not_accepted(monkeypatch, configured_client, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    response = configured_client.get("/admin/config?source=/tmp/config.yaml", headers=_headers())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "config_snapshot_invalid_request"
    assert source_spies.calls == []
    _assert_no_store(response)


def test_fixed_path_source_too_large_returns_degraded_snapshot(monkeypatch, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    response = _client(
        source_spies,
        load_litellm_text=lambda: "x" * (unified._MAX_SOURCE_BYTES + 1),
    ).get("/admin/config", headers=_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert {"source": "litellm-config", "code": "source_invalid"} in response.json()["errors"]
    assert response.json()["drift"]["status"] == "unknown"
    _assert_no_store(response)


@pytest.mark.parametrize(
    ("source", "expected_code"),
    [
        ("litellm", "source_unavailable"),
        ("registry", "source_unavailable"),
        ("runtime", "source_unavailable"),
    ],
)
def test_each_source_failure_is_safe_and_independent(monkeypatch, source_spies, source, expected_code):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")

    def fail_sync():
        raise RuntimeError("SECRET=https://credentials.example/private")

    async def fail_async():
        raise RuntimeError("SECRET=https://credentials.example/private")

    kwargs = {}
    if source == "litellm":
        kwargs["load_litellm_text"] = fail_sync
    elif source == "registry":
        kwargs["load_registry_model_ids"] = fail_sync
    elif source == "runtime":
        kwargs["fetch_runtime_model_ids"] = fail_async
    response = _client(source_spies, **kwargs).get("/admin/config", headers=_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert any(error["code"] == expected_code for error in response.json()["errors"])
    assert "credentials.example" not in response.text
    assert "SECRET" not in response.text
    _assert_no_store(response)


def test_environment_acquisition_failure_is_safe_orchestration_error(monkeypatch, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")

    def fail():
        raise RuntimeError("SECRET=https://credentials.example/private")

    response = _client(source_spies, environment=fail).get("/admin/config", headers=_headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "config_snapshot_unavailable"
    assert "credentials.example" not in response.text
    assert "SECRET" not in response.text
    _assert_no_store(response)


def test_source_timeout_returns_degraded_snapshot(monkeypatch, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    monkeypatch.setattr(unified, "_TOTAL_TIMEOUT_SECONDS", 0.01)

    async def slow_runtime() -> tuple[str, ...]:
        await unified.asyncio.sleep(0.1)
        return ("gpt-safe",)

    response = _client(source_spies, fetch_runtime_model_ids=slow_runtime).get("/admin/config", headers=_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["drift"]["status"] == "unknown"
    assert {"source": "runtime-visible-models", "code": "source_timeout"} in response.json()["errors"]
    _assert_no_store(response)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("loader_name", "source_id"),
    [
        ("load_litellm_text", "litellm-config"),
        ("load_registry_model_ids", "model-registry"),
    ],
)
async def test_blocking_sync_source_times_out_without_blocking_event_loop(
    monkeypatch,
    source_spies,
    loader_name,
    source_id,
):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    monkeypatch.setattr(unified, "_SOURCE_TIMEOUT_SECONDS", 0.01, raising=False)

    def stalled_source():
        time.sleep(0.15)
        return HEALTHY_YAML if loader_name == "load_litellm_text" else ("gpt-safe",)

    loaders = {
        "load_litellm_text": source_spies.litellm,
        "load_registry_model_ids": source_spies.registry,
    }
    loaders[loader_name] = stalled_source
    configure_unified_config_admin(
        UnifiedConfigAdminDeps(
            load_litellm_text=loaders["load_litellm_text"],
            load_registry_model_ids=loaders["load_registry_model_ids"],
            fetch_runtime_model_ids=source_spies.runtime,
            environment=source_spies.environment,
            now=source_spies.now,
        )
    )
    app = FastAPI()
    app.include_router(unified.router)

    started = time.monotonic()
    heartbeat = asyncio.create_task(asyncio.sleep(0.005))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        request = asyncio.create_task(client.get("/admin/config", headers=_headers()))
        await heartbeat
        heartbeat_elapsed = time.monotonic() - started
        response = await request

    assert heartbeat_elapsed < 0.05
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert {"source": source_id, "code": "source_timeout"} in response.json()["errors"]
    _assert_no_store(response)


@pytest.mark.asyncio
async def test_live_runtime_helper_receives_two_second_http_budget(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "gpt-safe"}]}

    class RecordingClient:
        timeout = None

        async def get(self, _url, *, headers, timeout):
            self.timeout = timeout
            assert headers == {}
            return Response()

    client = RecordingClient()
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    monkeypatch.setattr(
        admin_panels,
        "_deps",
        lambda: SimpleNamespace(get_http_client=lambda: client, litellm_url="http://litellm:4000"),
    )

    models, errors = await admin_panels._admin_fetch_visible_models()

    assert models == ["gpt-safe"]
    assert errors == []
    assert client.timeout == 2.0
    assert unified._TOTAL_TIMEOUT_SECONDS == 5.0
    assert not hasattr(unified, "_CONNECT_TIMEOUT_SECONDS")


def test_safe_logging_omits_raw_source_failures(monkeypatch, source_spies, caplog):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")

    def fail():
        raise RuntimeError("sk-super-secret https://private.example /root/config.yaml")

    with caplog.at_level(logging.INFO, logger="gateway-engine.config-snapshot"):
        response = _client(source_spies, load_registry_model_ids=fail).get("/admin/config", headers=_headers())
    assert response.status_code == 200
    assert "sk-super-secret" not in caplog.text
    assert "private.example" not in caplog.text
    assert "/root/config.yaml" not in caplog.text
    _assert_no_store(response)


def test_safe_logging_uses_builder_degraded_outcome(monkeypatch, source_spies, caplog):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    with caplog.at_level(logging.INFO, logger="gateway-engine.config-snapshot"):
        response = _client(source_spies, load_litellm_text=lambda: "model_list: [").get(
            "/admin/config", headers=_headers()
        )
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert "outcome=degraded" in caplog.text
    _assert_no_store(response)


def test_response_larger_than_64_kib_is_rejected_without_snapshot(monkeypatch, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    aliases = tuple(f"model-{index:03d}-" + ("a" * 480) for index in range(256))
    response = _client(
        source_spies,
        load_litellm_text=lambda: "model_list: []\n",
        load_registry_model_ids=lambda: aliases,
        fetch_runtime_model_ids=lambda: _async_value(aliases),
    ).get("/admin/config", headers=_headers())
    assert response.status_code == 502
    assert response.json() == {
        "error": {"code": "config_snapshot_too_large", "message": "Configuration snapshot is too large"}
    }
    assert "model-000" not in response.text
    _assert_no_store(response)


async def _async_value(value):
    return value


def test_unexpected_builder_failure_is_safe_503(monkeypatch, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    monkeypatch.setattr(
        unified,
        "build_config_snapshot",
        lambda _inputs: (_ for _ in ()).throw(RuntimeError("raw-secret-value")),
    )
    response = _client(source_spies).get("/admin/config", headers=_headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "config_snapshot_unavailable"
    assert "raw-secret-value" not in response.text
    _assert_no_store(response)


def test_feature_flag_is_evaluated_dynamically_for_rollback(monkeypatch, configured_client, source_spies):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    assert configured_client.get("/admin/config", headers=_headers()).status_code == 200
    source_spies.calls.clear()
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "false")
    response = configured_client.get("/admin/config", headers=_headers())
    assert response.status_code == 404
    assert source_spies.calls == []
    _assert_no_store(response)


def test_alias_flag_is_supported_and_primary_flag_takes_precedence(monkeypatch, configured_client):
    monkeypatch.delenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", raising=False)
    monkeypatch.setenv("GATEWAY_ENGINE_UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    assert configured_client.get("/admin/config", headers=_headers()).status_code == 200
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "false")
    assert configured_client.get("/admin/config", headers=_headers()).status_code == 404


def test_success_is_compact_json(monkeypatch, configured_client):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    response = configured_client.get("/admin/config", headers=_headers())
    assert b": " not in response.content
    assert b", " not in response.content
    assert len(response.content) <= unified._MAX_RESPONSE_BYTES
    _assert_no_store(response)


def test_openapi_routing_properties_use_bounded_scalar_union():
    openapi_path = next(
        (
            parent / "docs" / "openapi" / "gateway-engine.yaml"
            for parent in Path(__file__).resolve().parents
            if (parent / "docs" / "openapi" / "gateway-engine.yaml").exists()
        ),
        None,
    )
    if openapi_path is None:
        pytest.skip("repository docs are not mounted in the service test image")
    schemas = yaml.safe_load(openapi_path.read_text(encoding="utf-8"))["components"]["schemas"]
    scalar_schema = schemas["UnifiedConfigRouterScalar"]
    assert scalar_schema == {
        "anyOf": [
            {"type": "string", "maxLength": 512},
            {"type": "number"},
            {"type": "boolean"},
        ]
    }
    routing_properties = schemas["UnifiedConfigSnapshot"]["properties"]["routing"]["properties"]
    expected_reference = {"$ref": "#/components/schemas/UnifiedConfigRouterScalar"}
    assert routing_properties == {
        "routing_strategy": expected_reference,
        "cooldown_time": expected_reference,
        "allowed_fails": expected_reference,
        "num_retries": expected_reference,
    }
    assert all(option.get("type") not in {"array", "object"} for option in scalar_schema["anyOf"])
