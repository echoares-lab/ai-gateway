"""Unit tests for one safe model reconciliation operation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from core.model_reconciliation import (
    ModelReconciliationService,
    ReconciliationTrigger,
)
from core.model_registry import (
    ModelRegistryRecord,
    build_reconcile_resources,
)


def _model(model_id: str = "gpt-5-4", **updates) -> ModelRegistryRecord:
    record = ModelRegistryRecord(
        model_id=model_id,
        provider="openai",
        family="openai",
        upstream_model=model_id.replace("-", ".", 2),
        litellm_model=f"openai/{model_id.replace('-', '.', 2)}",
        enabled=True,
        status="HEALTHY",
        probe_status="healthy",
        probe_checked_at=datetime.now(timezone.utc),
    )
    return record.model_copy(update=updates)


class Fakes:
    def __init__(self, existing=None, discovered=None):
        self.models = list(existing or [])
        self.discovered = list(discovered or [])
        self.probed = []
        self.applied = []
        self.rollbacks = []
        self.reloads = 0
        self.catalog = {model.model_id for model in self.models if model.enabled}
        self.validation_error = None
        self.discovery_error = None
        self.reload_ok = True
        self.rendered_models = []

    async def discover(self):
        if self.discovery_error:
            raise self.discovery_error
        return self.discovered

    def list_models(self):
        return list(self.models)

    def upsert(self, models):
        by_id = {model.model_id: model for model in self.models}
        by_id.update({model.model_id: model for model in models})
        self.models = list(by_id.values())
        return len(models)

    async def probe(self, model):
        self.probed.append(model.model_id)
        return model.model_copy(update={"probe_status": "healthy", "status": "HEALTHY"})

    def render(self, models):
        self.rendered_models = list(models)
        return build_reconcile_resources(models)

    def validate(self, resources):
        if self.validation_error:
            raise self.validation_error

    async def apply(self, resources):
        self.applied.append(resources)
        return "previous-artifacts"

    async def rollback(self, token):
        self.rollbacks.append(token)

    async def reload(self):
        self.reloads += 1
        return self.reload_ok

    async def read_catalog(self):
        return set(self.catalog)

    def service(self):
        return ModelReconciliationService(
            discover=self.discover,
            list_models=self.list_models,
            upsert_models=self.upsert,
            probe_model=self.probe,
            render=self.render,
            validate=self.validate,
            apply=self.apply,
            rollback=self.rollback,
            reload=self.reload,
            read_catalog=self.read_catalog,
        )


@pytest.mark.asyncio
async def test_no_change_succeeds_without_apply_or_reload():
    current = _model(
        source="cliproxy",
        upstream_model="gpt-5.4",
        litellm_model="openai/gpt-5.4",
    )
    fakes = Fakes(existing=[current], discovered=[{"id": "gpt-5.4"}])

    result = await fakes.service().run(ReconciliationTrigger.SCHEDULED)

    assert result.outcome == "success"
    assert result.phase == "complete"
    assert result.counts == {
        "discovered": 1,
        "added": 0,
        "updated": 0,
        "enabled": 1,
        "disabled": 0,
        "unchanged": 1,
    }
    assert result.verification == "not_required"
    assert fakes.applied == []
    assert fakes.reloads == 0


@pytest.mark.asyncio
async def test_discovered_add_is_probed_applied_reloaded_and_verified():
    fakes = Fakes(discovered=[{"id": "AI-Gateway:gpt-5.6-sol"}])
    fakes.catalog = {"gpt-5-6-sol"}

    result = await fakes.service().run(ReconciliationTrigger.STARTUP)

    assert result.outcome == "success"
    assert result.counts["added"] == 1
    assert fakes.probed == ["gpt-5-6-sol"]
    assert len(fakes.applied) == 1
    assert fakes.reloads == 1
    assert result.verification == "verified"


@pytest.mark.asyncio
async def test_discovery_merge_preserves_curated_metadata():
    current = _model(
        policy_metadata={"manual_note": "keep", "api_base": "http://old"},
        supports_tools=True,
        cost_tier=3,
    )
    fakes = Fakes(existing=[current], discovered=[{"id": "AI-Gateway:gpt-5.4", "owned_by": "proxy"}])

    await fakes.service().run(ReconciliationTrigger.MANUAL, dry_run=True)

    merged = fakes.rendered_models[0]
    assert merged.policy_metadata["manual_note"] == "keep"
    assert merged.policy_metadata["owned_by"] == "proxy"
    assert merged.supports_tools is True
    assert merged.cost_tier == 3


@pytest.mark.asyncio
async def test_discovery_failure_is_bounded_and_stops_pipeline():
    fakes = Fakes()
    fakes.discovery_error = RuntimeError("secret=" + "x" * 1000)

    result = await fakes.service().run(ReconciliationTrigger.SCHEDULED)

    assert result.outcome == "failed"
    assert result.phase == "discover"
    assert len(result.errors) == 1
    assert len(result.errors[0]["message"]) <= 300
    assert fakes.applied == []


@pytest.mark.asyncio
async def test_validation_failure_prevents_apply_and_reload():
    fakes = Fakes(discovered=[{"id": "gpt-5.6-sol"}])
    fakes.validation_error = ValueError("invalid yaml")

    result = await fakes.service().run(ReconciliationTrigger.MANUAL)

    assert result.outcome == "failed"
    assert result.phase == "validate"
    assert fakes.applied == []
    assert fakes.reloads == 0


@pytest.mark.asyncio
async def test_reload_failure_rolls_back_applied_artifacts():
    fakes = Fakes(discovered=[{"id": "gpt-5.6-sol"}])
    fakes.reload_ok = False

    result = await fakes.service().run(ReconciliationTrigger.SCHEDULED)

    assert result.outcome == "degraded"
    assert result.phase == "reload"
    assert fakes.rollbacks == ["previous-artifacts"]
    assert fakes.reloads == 2
    assert result.verification == "rollback"


@pytest.mark.asyncio
async def test_final_catalog_verification_failure_rolls_back():
    fakes = Fakes(discovered=[{"id": "gpt-5.6-sol"}])
    fakes.catalog = set()

    result = await fakes.service().run(
        ReconciliationTrigger.DEMAND,
        requested_model="gpt-5-6-sol",
    )

    assert result.outcome == "degraded"
    assert result.phase == "verify"
    assert result.requested_model == "gpt-5-6-sol"
    assert result.verification == "failed"
    assert fakes.rollbacks == ["previous-artifacts"]
    assert fakes.reloads == 2
