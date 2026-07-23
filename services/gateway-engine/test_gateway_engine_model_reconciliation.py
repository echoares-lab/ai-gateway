"""Unit tests for one safe model reconciliation operation."""

from __future__ import annotations

import asyncio
import os
import stat
from datetime import datetime, timezone

import httpx
import pytest
from api.proxy_routing import is_unknown_model_response, maybe_enqueue_unknown_model_refresh
from core.metrics import (
    MODEL_RECONCILIATION_CHANGES,
    MODEL_RECONCILIATION_DURATION,
    MODEL_RECONCILIATION_RUNS,
    record_model_reconciliation,
)
from core.model_reconciliation import (
    ModelReconciliationService,
    ReconciliationArtifactManager,
    ReconciliationResult,
    ReconciliationTrigger,
    request_litellm_reload,
)
from core.model_registry import (
    ModelRegistryReconcileResource,
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


def test_reconciliation_metrics_use_only_bounded_labels():
    assert MODEL_RECONCILIATION_RUNS._labelnames == ("outcome", "trigger")
    assert MODEL_RECONCILIATION_DURATION._labelnames == ("outcome", "trigger")
    assert MODEL_RECONCILIATION_CHANGES._labelnames == ("change",)

    result = ReconciliationResult(
        outcome="unexpected-provider-text",
        phase="complete",
        trigger=ReconciliationTrigger.DEMAND,
        requested_model="secret-key-alias",
        counts={"added": 1, "updated": 2, "enabled": 3, "disabled": 4, "discovered": 5, "unchanged": 6},
        verification="verified",
        started_at=datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 7, 23, 10, 0, 2, tzinfo=timezone.utc),
        errors=[{"code": "x", "message": "Bearer sk-secret", "phase": "complete"}],
    )

    record_model_reconciliation(result)

    samples = [sample for metric in MODEL_RECONCILIATION_RUNS.collect() for sample in metric.samples]
    assert any(sample.labels == {"outcome": "unknown", "trigger": "demand"} for sample in samples)
    assert all("secret-key-alias" not in str(sample.labels) for sample in samples)
    assert all("sk-secret" not in str(sample.labels) for sample in samples)


async def _wait_until(predicate, *, timeout=0.5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def _resource(name, content):
    return ModelRegistryReconcileResource(name=name, kind="yaml", changed=True, content=content)


@pytest.mark.parametrize(
    "status, body, expected",
    [
        (
            400,
            {"error": {"message": "/chat/completions: Invalid model name passed in model=gpt-5-6-sol"}},
            True,
        ),
        (404, {"error": {"provider_specific_fields": {"error": "model not found"}}}, True),
        (400, {"error": {"message": "invalid request body"}}, False),
        (401, {"error": {"message": "invalid model name"}}, False),
        (429, {"error": {"message": "invalid model name"}}, False),
        (503, {"error": {"message": "invalid model name"}}, False),
        (400, {"message": "invalid model name"}, False),
        (400, {"error": {"message": "invalid model name" + ("x" * 9000)}}, False),
    ],
)
def test_unknown_model_response_classifier_is_typed_and_status_bounded(status, body, expected):
    response = httpx.Response(status, json=body)
    assert is_unknown_model_response(response) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("validated, model", [(False, "gpt-5.6-sol"), (True, "bad model/name")])
async def test_unknown_model_refresh_rejects_unauthenticated_or_invalid_model(validated, model):
    requested = []

    async def request_refresh(trigger, requested_model):
        requested.append((trigger, requested_model))

    response = httpx.Response(400, json={"error": {"message": "Invalid model name passed"}})
    returned = maybe_enqueue_unknown_model_refresh(
        response,
        model,
        client_auth="sk-client" if validated else None,
        validate_auth=lambda _token: validated,
        request_refresh=request_refresh,
    )
    await asyncio.sleep(0)

    assert returned is response
    assert requested == []


@pytest.mark.asyncio
@pytest.mark.parametrize("client_auth", ["", "   ", "Bearer ", "junk", "ak-tenant-workspace-team-repo-dev"])
async def test_unknown_model_refresh_requires_successful_explicit_auth_validation(client_auth):
    requested = []

    async def request_refresh(trigger, requested_model):
        requested.append((trigger, requested_model))

    response = httpx.Response(400, json={"error": {"message": "Invalid model name passed"}})
    returned = maybe_enqueue_unknown_model_refresh(
        response,
        "gpt-5.6-sol",
        client_auth=client_auth,
        validate_auth=lambda _token: False,
        request_refresh=request_refresh,
    )
    await asyncio.sleep(0)

    assert returned is response
    assert requested == []


@pytest.mark.asyncio
async def test_unknown_model_refresh_is_async_and_returns_original_stream_error_unchanged():
    release = asyncio.Event()
    requested = []

    async def request_refresh(trigger, requested_model):
        requested.append((trigger, requested_model))
        await release.wait()

    content = b'{"error":{"message":"Invalid model name passed in model=gpt-5-6-sol"}}'
    response = httpx.Response(400, content=content, headers={"x-upstream": "original"})
    returned = maybe_enqueue_unknown_model_refresh(
        response,
        "gpt-5.6-sol",
        client_auth="sk-client",
        validate_auth=lambda _token: True,
        request_refresh=request_refresh,
    )
    await asyncio.sleep(0)

    assert returned is response
    assert returned.content == content
    assert returned.headers["x-upstream"] == "original"
    assert requested == [(ReconciliationTrigger.DEMAND, "gpt-5-6-sol")]
    release.set()


@pytest.mark.asyncio
async def test_unknown_model_refresh_enqueue_failure_does_not_change_response():
    response = httpx.Response(400, json={"error": {"message": "Invalid model name passed"}})

    def failed_enqueue(trigger, requested_model):
        raise RuntimeError("scheduler unavailable")

    returned = maybe_enqueue_unknown_model_refresh(
        response,
        "gpt-5.6-sol",
        client_auth="sk-client",
        validate_auth=lambda _token: True,
        request_refresh=failed_enqueue,
    )
    await asyncio.sleep(0)

    assert returned is response


def test_atomic_apply_preserves_modes_and_returns_restorable_bytes(tmp_path):
    litellm = tmp_path / "litellm.yaml"
    gemini = tmp_path / "gemini.json"
    litellm.write_bytes(b"old-litellm")
    gemini.write_bytes(b"old-gemini")
    litellm.chmod(0o640)
    gemini.chmod(0o600)
    manager = ReconciliationArtifactManager({"litellm-config.yaml": litellm, "gemini-model-map.json": gemini})

    token = manager.apply(
        [_resource("litellm-config.yaml", "new-litellm"), _resource("gemini-model-map.json", "new-gemini")]
    )

    assert litellm.read_bytes() == b"new-litellm"
    assert gemini.read_bytes() == b"new-gemini"
    assert stat.S_IMODE(litellm.stat().st_mode) == 0o640
    assert stat.S_IMODE(gemini.stat().st_mode) == 0o600
    assert token.snapshots["litellm-config.yaml"].content == b"old-litellm"
    assert token.snapshots["gemini-model-map.json"].content == b"old-gemini"


def test_partial_apply_failure_restores_already_replaced_files(tmp_path, monkeypatch):
    litellm = tmp_path / "litellm.yaml"
    gemini = tmp_path / "gemini.json"
    litellm.write_bytes(b"old-litellm")
    gemini.write_bytes(b"old-gemini")
    manager = ReconciliationArtifactManager({"litellm-config.yaml": litellm, "gemini-model-map.json": gemini})
    real_replace = os.replace
    replacements = 0

    def fail_second_replace(source, destination):
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("second replace failed")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="second replace failed"):
        manager.apply(
            [_resource("litellm-config.yaml", "new-litellm"), _resource("gemini-model-map.json", "new-gemini")]
        )

    assert litellm.read_bytes() == b"old-litellm"
    assert gemini.read_bytes() == b"old-gemini"


def test_explicit_rollback_restores_existing_and_removes_new_files(tmp_path):
    litellm = tmp_path / "litellm.yaml"
    gemini = tmp_path / "gemini.json"
    litellm.write_bytes(b"old-litellm")
    manager = ReconciliationArtifactManager({"litellm-config.yaml": litellm, "gemini-model-map.json": gemini})
    token = manager.apply(
        [_resource("litellm-config.yaml", "new-litellm"), _resource("gemini-model-map.json", "new-gemini")]
    )

    manager.rollback(token)

    assert litellm.read_bytes() == b"old-litellm"
    assert not gemini.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code, expected", [(200, True), (500, False)])
async def test_litellm_reload_reports_http_success_or_failure(status_code, expected):
    class Client:
        async def post(self, url, **kwargs):
            assert url == "http://litellm:4000/config/update"
            assert kwargs["headers"] == {"authorization": "Bearer master"}
            return type("Response", (), {"status_code": status_code})()

    assert await request_litellm_reload(Client(), "http://litellm:4000", "master", timeout_sec=0.1) is expected


@pytest.mark.asyncio
async def test_litellm_reload_timeout_returns_false():
    class Client:
        async def post(self, url, **kwargs):
            await asyncio.Event().wait()

    assert await request_litellm_reload(Client(), "http://litellm:4000", "master", timeout_sec=0.01) is False


@pytest.mark.asyncio
async def test_litellm_reload_with_empty_master_key_fails_before_request():
    class Client:
        def __init__(self):
            self.calls = 0

        async def post(self, url, **kwargs):
            self.calls += 1
            raise AssertionError("reload request must not be sent without authentication")

    client = Client()

    assert await request_litellm_reload(client, "http://litellm:4000", "", timeout_sec=0.1) is False
    assert client.calls == 0


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
        self.upsert_error = None

    async def discover(self):
        if self.discovery_error:
            raise self.discovery_error
        return self.discovered

    def list_models(self):
        return list(self.models)

    def upsert(self, models):
        if self.upsert_error:
            raise self.upsert_error
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

    def service(self, **scheduler_options):
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
            **scheduler_options,
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
async def test_unhealthy_discovered_add_remains_disabled_and_is_not_rendered():
    fakes = Fakes(discovered=[{"id": "AI-Gateway:gpt-5.6-sol"}])

    async def unhealthy_probe(model):
        fakes.probed.append(model.model_id)
        assert model.enabled is False
        assert model.status == "PENDING"
        return model.model_copy(update={"probe_status": "unhealthy", "status": "UNHEALTHY"})

    fakes.probe = unhealthy_probe
    result = await fakes.service().run(ReconciliationTrigger.STARTUP)

    assert result.outcome == "success"
    assert result.models[0].enabled is False
    assert result.counts["enabled"] == 0
    assert result.counts["disabled"] == 1
    litellm_resource = next(resource for resource in result.resources if resource.kind == "yaml")
    assert "gpt-5-6-sol" not in litellm_resource.content


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
async def test_discovery_merge_preserves_curated_metadata_when_discovery_value_is_empty():
    current = _model(policy_metadata={"owned_by": "curated-owner", "manual_note": "keep"})
    fakes = Fakes(existing=[current], discovered=[{"id": "AI-Gateway:gpt-5.4", "owned_by": None}])

    await fakes.service().run(ReconciliationTrigger.MANUAL, dry_run=True)

    merged = fakes.rendered_models[0]
    assert merged.policy_metadata["owned_by"] == "curated-owner"
    assert merged.policy_metadata["manual_note"] == "keep"


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
async def test_upsert_failure_after_verification_rolls_back_artifacts():
    fakes = Fakes(discovered=[{"id": "gpt-5.6-sol"}])
    fakes.catalog = {"gpt-5-6-sol"}
    fakes.upsert_error = RuntimeError("database unavailable")

    result = await fakes.service().run(ReconciliationTrigger.MANUAL)

    assert result.outcome == "degraded"
    assert result.phase == "persist"
    assert result.errors[0]["code"] == "persist_failed"
    assert fakes.rollbacks == ["previous-artifacts"]
    assert fakes.reloads == 2
    assert fakes.models == []


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
async def test_reload_failure_does_not_persist_registry_and_next_run_retries():
    fakes = Fakes(discovered=[{"id": "gpt-5.6-sol"}])
    fakes.catalog = {"gpt-5-6-sol"}
    fakes.reload_ok = False

    failed = await fakes.service().run(ReconciliationTrigger.SCHEDULED)

    assert failed.outcome == "degraded"
    assert fakes.models == []

    fakes.reload_ok = True
    succeeded = await fakes.service().run(ReconciliationTrigger.SCHEDULED)

    assert succeeded.outcome == "success"
    assert succeeded.counts["added"] == 1
    assert [model.model_id for model in fakes.models] == ["gpt-5-6-sol"]


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


@pytest.mark.asyncio
async def test_scheduler_runs_after_startup_delay_and_then_periodically():
    fakes = Fakes()
    service = fakes.service(startup_delay_sec=0.01, interval_sec=0.01)
    triggers = []

    async def record_run(trigger, requested_model=None, *, dry_run=False):
        triggers.append(trigger)

    service.run = record_run
    service.start()
    await _wait_until(lambda: len(triggers) >= 2)
    await service.stop()

    assert triggers[:2] == [ReconciliationTrigger.STARTUP, ReconciliationTrigger.SCHEDULED]


@pytest.mark.asyncio
async def test_scheduler_stop_cancels_and_awaits_background_task():
    fakes = Fakes()
    service = fakes.service(startup_delay_sec=60)
    service.start()
    task = service.scheduler_task

    await service.stop()

    assert task is not None
    assert task.done()
    assert service.scheduler_task is None


@pytest.mark.asyncio
async def test_disabled_scheduler_does_not_start_or_accept_requests():
    service = Fakes().service(enabled=False)

    assert service.start() is None
    assert await service.request(ReconciliationTrigger.MANUAL) is False
    assert service.scheduler_task is None


@pytest.mark.asyncio
async def test_active_requests_coalesce_to_one_pending_rerun():
    service = Fakes().service(startup_delay_sec=60)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def blocking_run(trigger, requested_model=None, *, dry_run=False):
        calls.append((trigger, requested_model))
        started.set()
        await release.wait()

    service.run = blocking_run
    service.start()
    assert await service.request(ReconciliationTrigger.MANUAL) is True
    await started.wait()
    assert await service.request(ReconciliationTrigger.SCHEDULED) is True
    assert await service.request(ReconciliationTrigger.DEMAND, "gpt-5-6") is True
    release.set()
    await _wait_until(lambda: len(calls) == 2)
    await service.stop()

    assert calls == [
        (ReconciliationTrigger.MANUAL, None),
        (ReconciliationTrigger.DEMAND, "gpt-5-6"),
    ]


@pytest.mark.asyncio
async def test_expedited_requests_are_rate_limited():
    service = Fakes().service(startup_delay_sec=60, expedited_min_interval_sec=60)
    calls = []

    async def record_run(trigger, requested_model=None, *, dry_run=False):
        calls.append((trigger, requested_model))

    service.run = record_run
    service.start()
    assert await service.request(ReconciliationTrigger.DEMAND, "gpt-5-6") is True
    await _wait_until(lambda: len(calls) == 1)
    assert await service.request(ReconciliationTrigger.DEMAND, "gpt-5-7") is False
    await service.stop()


@pytest.mark.asyncio
async def test_scheduler_reports_timeout_as_a_bounded_result():
    service = Fakes().service(startup_delay_sec=60, timeout_sec=0.01)
    blocker = asyncio.Event()

    async def blocked_run(trigger, requested_model=None, *, dry_run=False):
        await blocker.wait()

    service.run = blocked_run
    service.start()
    assert await service.request(ReconciliationTrigger.MANUAL) is True
    await _wait_until(lambda: service.last_result is not None)
    await service.stop()

    assert service.last_result.outcome == "failed"
    assert service.last_result.phase == "timeout"
    assert service.last_result.errors == [
        {"code": "timeout", "message": "reconciliation exceeded 0.01 seconds", "phase": "timeout"}
    ]


@pytest.mark.asyncio
async def test_scheduler_timeout_rolls_back_artifacts_applied_by_cancelled_run():
    fakes = Fakes(discovered=[{"id": "gpt-5.6-sol"}])
    reload_started = asyncio.Event()
    reload_calls = 0

    async def blocking_first_reload():
        nonlocal reload_calls
        reload_calls += 1
        if reload_calls == 1:
            reload_started.set()
            await asyncio.Event().wait()
        return True

    fakes.reload = blocking_first_reload
    service = fakes.service(startup_delay_sec=60, timeout_sec=0.01)
    service.start()

    assert await service.request(ReconciliationTrigger.MANUAL) is True
    await reload_started.wait()
    await _wait_until(lambda: service.last_result is not None)
    await service.stop()

    assert service.last_result.phase == "timeout"
    assert fakes.rollbacks == ["previous-artifacts"]
    assert reload_calls == 2


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_the_reconciliation_service(monkeypatch):
    import main

    events = []

    class FakeClient:
        async def aclose(self):
            events.append("client_closed")

    class FakeService:
        def start(self):
            events.append("started")

        async def stop(self):
            events.append("stopped")

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(main, "CACHE_ENABLED", False)
    monkeypatch.setattr(main, "POLICY_ENGINE_ENABLED", False)
    monkeypatch.setattr(main, "GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED", False)
    monkeypatch.setattr(main, "GATEWAY_ENGINE_MODEL_RECONCILIATION_ENABLED", True)
    monkeypatch.setattr(main, "_model_reconciliation_service", FakeService())

    async with main._lifespan(main.app):
        assert events == ["started"]

    assert events == ["started", "stopped", "client_closed"]


def test_concrete_factory_uses_configured_artifacts_admin_client_and_defaults(monkeypatch, tmp_path):
    import main

    litellm = tmp_path / "litellm.yaml"
    gemini = tmp_path / "gemini.json"
    litellm.write_text(
        "model_list: []\n"
        "general_settings:\n  master_key: os.environ/LITELLM_MASTER_KEY\n"
        "litellm_settings:\n  cache: true\n"
    )
    gemini.write_text("{}\n")

    class Store:
        def list_models(self):
            return type("Loaded", (), {"registry_available": True, "models": [], "errors": []})()

        def upsert_models(self, models):
            return len(models)

    monkeypatch.setattr(main, "LITELLM_CONFIG_PATH", str(litellm))
    monkeypatch.setattr(main, "GEMINI_MODEL_MAP_PATH", str(gemini))
    monkeypatch.setattr(main, "_model_registry_store", lambda: Store())
    monkeypatch.setattr(main, "_client", object())

    service = main._build_model_reconciliation_service()

    assert isinstance(service, ModelReconciliationService)
    assert service.enabled is True
    assert service.startup_delay_sec == 30
    assert service.interval_sec == 900
    assert service.expedited_min_interval_sec == 60
    assert service.timeout_sec == 120
    resources = service._render([])
    rendered_litellm = next(resource for resource in resources if resource.name == "litellm-config.yaml")
    rendered_doc = __import__("yaml").safe_load(rendered_litellm.content)
    assert rendered_doc["general_settings"] == {"master_key": "os.environ/LITELLM_MASTER_KEY"}
    assert rendered_doc["litellm_settings"]["cache"] is True
    token = service._apply(resources)
    assert token.snapshots == {}


@pytest.mark.asyncio
async def test_lifespan_builds_and_owns_the_concrete_singleton(monkeypatch):
    import main

    events = []

    class FakeClient:
        async def aclose(self):
            events.append("client_closed")

    class FakeService:
        def start(self):
            events.append("started")

        async def stop(self):
            events.append("stopped")

    service = FakeService()
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(main, "CACHE_ENABLED", False)
    monkeypatch.setattr(main, "POLICY_ENGINE_ENABLED", False)
    monkeypatch.setattr(main, "GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED", False)
    monkeypatch.setattr(main, "GATEWAY_ENGINE_MODEL_RECONCILIATION_ENABLED", True)
    monkeypatch.setattr(main, "_model_reconciliation_service", None)
    monkeypatch.setattr(main, "_build_model_reconciliation_service", lambda: service)

    async with main._lifespan(main.app):
        assert main._model_reconciliation_service is service
        assert events == ["started"]

    assert events == ["started", "stopped", "client_closed"]


@pytest.mark.asyncio
async def test_lifespan_stops_reconciliation_when_application_raises(monkeypatch):
    import main

    events = []

    class FakeClient:
        async def aclose(self):
            events.append("client_closed")

    class FakeService:
        def start(self):
            events.append("started")

        async def stop(self):
            events.append("stopped")

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    monkeypatch.setattr(main, "CACHE_ENABLED", False)
    monkeypatch.setattr(main, "POLICY_ENGINE_ENABLED", False)
    monkeypatch.setattr(main, "GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED", False)
    monkeypatch.setattr(main, "GATEWAY_ENGINE_MODEL_RECONCILIATION_ENABLED", True)
    monkeypatch.setattr(main, "_model_reconciliation_service", FakeService())

    with pytest.raises(RuntimeError, match="application failed"):
        async with main._lifespan(main.app):
            raise RuntimeError("application failed")

    assert events == ["started", "stopped", "client_closed"]
