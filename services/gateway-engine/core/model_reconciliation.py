"""Safe, collaborator-driven model reconciliation orchestration."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from core.model_registry import (
    ModelRegistryRecord,
    diff_discovered_models,
    merge_discovered_model,
    record_from_cliproxy_model,
)

_MAX_ERRORS = 10
_MAX_ERROR_MESSAGE = 300


class ReconciliationTrigger(str, Enum):
    STARTUP = "startup"
    SCHEDULED = "scheduled"
    DEMAND = "demand"
    MANUAL = "manual"


@dataclass
class ReconciliationResult:
    outcome: str
    phase: str
    trigger: ReconciliationTrigger
    requested_model: str | None
    counts: dict[str, int]
    verification: str
    started_at: datetime
    completed_at: datetime
    errors: list[dict[str, str]] = field(default_factory=list)
    models: list[ModelRegistryRecord] = field(default_factory=list)
    resources: Any = None
    diffs: list[dict[str, Any]] = field(default_factory=list)


async def _resolve(value):
    if inspect.isawaitable(value):
        return await value
    return value


class ModelReconciliationService:
    """Run one reconciliation without owning scheduling or concrete I/O."""

    def __init__(
        self,
        *,
        discover: Callable[[], Any],
        list_models: Callable[[], Any],
        upsert_models: Callable[[list[ModelRegistryRecord]], Any],
        probe_model: Callable[[ModelRegistryRecord], Any],
        render: Callable[[list[ModelRegistryRecord]], Any],
        validate: Callable[[Any], Any],
        apply: Callable[[Any], Any],
        rollback: Callable[[Any], Any],
        reload: Callable[[], Any],
        read_catalog: Callable[[], Any],
        probe_is_stale: Callable[[ModelRegistryRecord], bool] | None = None,
    ):
        self._discover = discover
        self._list_models = list_models
        self._upsert_models = upsert_models
        self._probe_model = probe_model
        self._render = render
        self._validate = validate
        self._apply = apply
        self._rollback = rollback
        self._reload = reload
        self._read_catalog = read_catalog
        self._probe_is_stale = probe_is_stale or (lambda model: model.probe_status is None)

    async def run(
        self,
        trigger: ReconciliationTrigger,
        requested_model: str | None = None,
        *,
        dry_run: bool = False,
    ) -> ReconciliationResult:
        started_at = datetime.now(timezone.utc)
        phase = "discover"
        counts = {
            "discovered": 0,
            "added": 0,
            "updated": 0,
            "enabled": 0,
            "disabled": 0,
            "unchanged": 0,
        }
        errors: list[dict[str, str]] = []
        verification = "not_run"
        rollback_token: Any = None
        result_models: list[ModelRegistryRecord] = []
        result_resources: Any = None
        result_diffs: list[dict[str, Any]] = []

        def finish(outcome: str, final_phase: str | None = None) -> ReconciliationResult:
            return ReconciliationResult(
                outcome=outcome,
                phase=final_phase or phase,
                trigger=trigger,
                requested_model=requested_model,
                counts=counts,
                verification=verification,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                errors=errors,
                models=result_models,
                resources=result_resources,
                diffs=result_diffs,
            )

        def record_error(code: str, exc: Exception | str) -> None:
            if len(errors) >= _MAX_ERRORS:
                return
            message = str(exc).replace("\n", " ")[:_MAX_ERROR_MESSAGE]
            errors.append({"code": code, "message": message, "phase": phase})

        try:
            raw_discovered = await _resolve(self._discover())
            discovered: list[ModelRegistryRecord] = []
            for item in raw_discovered:
                if isinstance(item, ModelRegistryRecord):
                    discovered.append(item)
                elif isinstance(item, dict):
                    record = record_from_cliproxy_model(item)
                    if record is not None:
                        discovered.append(record)
                else:
                    raise TypeError("discovery returned an unsupported model record")
            counts["discovered"] = len(discovered)
        except Exception as exc:
            record_error("discovery_failed", exc)
            return finish("failed")

        try:
            phase = "merge"
            current = await _resolve(self._list_models())
            current_by_id = {model.model_id: model for model in current}
            diffs = diff_discovered_models(discovered, current)
            result_diffs = diffs
            counts["added"] = sum(diff["kind"] == "add" for diff in diffs)
            counts["updated"] = sum(diff["kind"] == "update" for diff in diffs)
            changed_ids = {diff["model_id"] for diff in diffs}
            counts["unchanged"] = len(discovered) - len(changed_ids)
            merged_discovered = [
                merge_discovered_model(model, current_by_id.get(model.model_id)) for model in discovered
            ]
            merged_by_id = dict(current_by_id)
            merged_by_id.update({model.model_id: model for model in merged_discovered})

            phase = "probe"
            additions = {diff["model_id"] for diff in diffs if diff["kind"] == "add"}
            probed_ids: set[str] = set()
            for model_id, model in list(merged_by_id.items()):
                if model_id in additions or self._probe_is_stale(model):
                    merged_by_id[model_id] = await _resolve(self._probe_model(model))
                    probed_ids.add(model_id)

            models = list(merged_by_id.values())
            discovered_ids = [model.model_id for model in discovered]
            persisted_ids = [*discovered_ids, *sorted(probed_ids - set(discovered_ids))]
            result_models = [merged_by_id[model_id] for model_id in persisted_ids]
            counts["enabled"] = sum(model.enabled for model in models)
            counts["disabled"] = len(models) - counts["enabled"]

            phase = "render"
            resources = await _resolve(self._render(models))
            result_resources = resources
            phase = "validate"
            validation_result = await _resolve(self._validate(resources))
            if validation_result is False:
                raise ValueError("rendered resources failed validation")

            if dry_run:
                verification = "dry_run"
                return finish("success", "complete")

            await _resolve(self._upsert_models(result_models))
            if not changed_ids:
                verification = "not_required"
                return finish("success", "complete")

            phase = "apply"
            rollback_token = await _resolve(self._apply(resources))
            phase = "reload"
            if not await _resolve(self._reload()):
                raise RuntimeError("LiteLLM reload failed")

            phase = "verify"
            catalog = set(await _resolve(self._read_catalog()))
            expected = {
                model.model_id for model in merged_by_id.values() if model.enabled and model.model_id in changed_ids
            }
            missing = sorted(expected - catalog)
            if missing:
                verification = "failed"
                raise RuntimeError(f"reconciled models missing from catalog: {', '.join(missing)}")
            verification = "verified"
            return finish("success", "complete")
        except Exception as exc:
            failed_phase = phase
            record_error(f"{phase}_failed", exc)
            if rollback_token is not None:
                try:
                    await _resolve(self._rollback(rollback_token))
                    await _resolve(self._reload())
                    if verification != "failed":
                        verification = "rollback"
                except Exception as rollback_exc:
                    phase = "rollback"
                    record_error("rollback_failed", rollback_exc)
            return finish("degraded" if rollback_token is not None else "failed", failed_phase)
