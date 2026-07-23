"""Mock end-to-end coverage for automatic model reconciliation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import main as gateway_engine_main
import pytest
import yaml
from core.model_reconciliation import (
    ModelReconciliationService,
    ReconciliationArtifactManager,
    ReconciliationTrigger,
)
from core.model_registry import ModelRegistryRecord, build_reconcile_resources

pytestmark = [pytest.mark.mock, pytest.mark.asyncio]

CLIPROXY_URL = "http://cliproxy:8317"
LITELLM_URL = "http://litellm:4000"
NEW_UPSTREAM_MODEL = "gpt-5.6-sol"
NEW_GATEWAY_ALIAS = "gpt-5-6-sol"


class InMemoryRegistry:
    def __init__(self):
        self.models: dict[str, ModelRegistryRecord] = {}

    def list_models(self):
        return list(self.models.values())

    def upsert_models(self, models):
        self.models.update({model.model_id: model for model in models})
        return len(models)


def build_service(tmp_path, client, registry, reload_catalog):
    litellm_path = tmp_path / "litellm-config.yaml"
    gemini_path = tmp_path / "gemini-model-map.json"
    litellm_path.write_text("model_list: []\n", encoding="utf-8")
    gemini_path.write_text("{}\n", encoding="utf-8")
    artifacts = ReconciliationArtifactManager(
        {
            "litellm-config.yaml": litellm_path,
            "gemini-model-map.json": gemini_path,
        }
    )

    async def discover():
        response = await client.get(f"{CLIPROXY_URL}/v1/models")
        response.raise_for_status()
        return response.json()["data"]

    async def probe(model):
        return model.model_copy(
            update={
                "status": "HEALTHY",
                "probe_status": "healthy",
                "probe_http_status": 200,
                "probe_checked_at": datetime.now(timezone.utc),
            }
        )

    def render(models):
        return build_reconcile_resources(
            models,
            current_litellm_config=litellm_path.read_text(encoding="utf-8"),
            current_gemini_map=gemini_path.read_text(encoding="utf-8"),
        )

    def validate(resources):
        for resource in resources:
            (yaml.safe_load if resource.kind == "yaml" else json.loads)(resource.content)
        return True

    async def reload():
        response = await client.post(f"{LITELLM_URL}/config/update")
        if response.is_success:
            reload_catalog()
        return response.is_success

    async def read_catalog():
        response = await client.get(f"{LITELLM_URL}/v1/models")
        response.raise_for_status()
        return {model["id"] for model in response.json()["data"]}

    return ModelReconciliationService(
        discover=discover,
        list_models=registry.list_models,
        upsert_models=registry.upsert_models,
        probe_model=probe,
        render=render,
        validate=validate,
        apply=artifacts.apply,
        rollback=artifacts.rollback,
        reload=reload,
        read_catalog=read_catalog,
        probe_is_stale=lambda model: False,
    )


async def test_cliproxy_new_gpt_reconciles_reloads_and_appears_as_gateway_alias(
    asgi_client, mock_litellm_router, tmp_path
):
    registry = InMemoryRegistry()
    catalog: list[str] = []
    reload_calls = 0

    mock_litellm_router.get(f"{CLIPROXY_URL}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": NEW_UPSTREAM_MODEL}]})
    )

    def reload_catalog():
        nonlocal reload_calls
        reload_calls += 1
        catalog[:] = [NEW_GATEWAY_ALIAS]

    mock_litellm_router.post("/config/update").mock(return_value=httpx.Response(200))
    mock_litellm_router.get("/v1/models").mock(
        side_effect=lambda request: httpx.Response(200, json={"data": [{"id": model} for model in catalog]})
    )
    service = build_service(tmp_path, gateway_engine_main._client, registry, reload_catalog)

    result = await service.run(ReconciliationTrigger.SCHEDULED)
    response = await asgi_client.get("/v1/models")

    assert result.outcome == "success", result.errors
    assert result.verification == "verified"
    assert any(resource.changed for resource in result.resources)
    assert NEW_UPSTREAM_MODEL in next(
        resource.content for resource in result.resources if resource.name == "litellm-config.yaml"
    )
    assert reload_calls == 1
    assert NEW_GATEWAY_ALIAS in registry.models
    assert [model["id"] for model in response.json()["data"]] == [f"AI-Gateway:{NEW_GATEWAY_ALIAS}"]


async def test_client_supplied_model_absent_from_cliproxy_is_never_added(asgi_client, mock_litellm_router, tmp_path):
    invented_model = "gpt-9-9-client-invented"
    registry = InMemoryRegistry()
    reload_calls = 0

    mock_litellm_router.get(f"{CLIPROXY_URL}/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))

    def reload_catalog():
        nonlocal reload_calls
        reload_calls += 1

    service = build_service(tmp_path, gateway_engine_main._client, registry, reload_catalog)

    result = await service.run(ReconciliationTrigger.DEMAND, requested_model=invented_model)
    response = await asgi_client.get("/v1/models")

    assert result.outcome == "success", result.errors
    assert invented_model not in registry.models
    assert reload_calls == 0
    assert f"AI-Gateway:{invented_model}" not in {model["id"] for model in response.json()["data"]}
