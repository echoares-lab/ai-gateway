"""Safe, collaborator-driven model reconciliation orchestration."""

from __future__ import annotations

import asyncio
import inspect
import os
import stat
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from core.model_registry import (
    ModelRegistryRecord,
    diff_discovered_models,
    merge_discovered_model,
    record_from_cliproxy_model,
)

_MAX_ERRORS = 10
_MAX_ERROR_MESSAGE = 300


@dataclass(frozen=True)
class ArtifactSnapshot:
    path: Path
    existed: bool
    content: bytes
    mode: int


@dataclass(frozen=True)
class ArtifactRollbackToken:
    snapshots: dict[str, ArtifactSnapshot]


class ReconciliationArtifactManager:
    """Atomically replace known reconciliation artifacts with rollback support."""

    def __init__(self, paths: Mapping[str, str | Path]):
        self._paths = {name: Path(path) for name, path in paths.items()}

    def apply(self, resources) -> ArtifactRollbackToken:
        changed = [resource for resource in resources if resource.changed]
        unknown = [resource.name for resource in changed if resource.name not in self._paths]
        if unknown:
            raise ValueError(f"unknown reconciliation artifact: {', '.join(unknown)}")

        snapshots = {resource.name: self._snapshot(self._paths[resource.name]) for resource in changed}
        token = ArtifactRollbackToken(snapshots=snapshots)
        replaced: list[str] = []
        try:
            for resource in changed:
                snapshot = snapshots[resource.name]
                self._atomic_write(snapshot.path, resource.content.encode("utf-8"), snapshot.mode)
                replaced.append(resource.name)
        except Exception:
            self.rollback(
                ArtifactRollbackToken(
                    snapshots={name: snapshots[name] for name in replaced},
                )
            )
            raise
        return token

    def rollback(self, token: ArtifactRollbackToken) -> None:
        for snapshot in token.snapshots.values():
            if snapshot.existed:
                self._atomic_write(snapshot.path, snapshot.content, snapshot.mode)
            else:
                snapshot.path.unlink(missing_ok=True)

    @staticmethod
    def _snapshot(path: Path) -> ArtifactSnapshot:
        try:
            file_stat = path.stat()
            return ArtifactSnapshot(
                path=path,
                existed=True,
                content=path.read_bytes(),
                mode=stat.S_IMODE(file_stat.st_mode),
            )
        except FileNotFoundError:
            return ArtifactSnapshot(path=path, existed=False, content=b"", mode=0o600)

    @staticmethod
    def _atomic_write(path: Path, content: bytes, mode: int) -> None:
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
                temporary_path = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, mode)
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                Path(temporary_path).unlink(missing_ok=True)


async def request_litellm_reload(
    client,
    litellm_url: str,
    master_key: str,
    *,
    timeout_sec: float,
) -> bool:
    """Request LiteLLM's authenticated config reload within a hard timeout."""
    if client is None:
        return False
    headers = {"authorization": f"Bearer {master_key}"} if master_key else {}
    try:
        async with asyncio.timeout(timeout_sec):
            response = await client.post(
                f"{litellm_url.rstrip('/')}/config/update",
                headers=headers,
                json={},
                timeout=timeout_sec,
            )
        return 200 <= response.status_code < 300
    except Exception:
        return False


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
    persisted_count: int = 0


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
        enabled: bool = True,
        startup_delay_sec: float = 30,
        interval_sec: float = 900,
        expedited_min_interval_sec: float = 60,
        timeout_sec: float = 120,
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
        self.enabled = enabled
        self.startup_delay_sec = max(0, startup_delay_sec)
        self.interval_sec = max(0, interval_sec)
        self.expedited_min_interval_sec = max(0, expedited_min_interval_sec)
        self.timeout_sec = max(0, timeout_sec)
        self._scheduler_task: asyncio.Task | None = None
        self._scheduler_lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._pending: tuple[ReconciliationTrigger, str | None] | None = None
        self._active = False
        self._last_expedited_at: float | None = None
        self.last_result: ReconciliationResult | None = None

    @property
    def scheduler_task(self) -> asyncio.Task | None:
        return self._scheduler_task

    def start(self) -> asyncio.Task | None:
        """Start the cancellable scheduler once when reconciliation is enabled."""
        if not self.enabled:
            return None
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        return self._scheduler_task

    async def stop(self) -> None:
        """Cancel and await the scheduler and any reconciliation it owns."""
        task = self._scheduler_task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if self._scheduler_task is task:
            self._scheduler_task = None

    async def request(
        self,
        trigger: ReconciliationTrigger,
        requested_model: str | None = None,
    ) -> bool:
        """Queue at most one rerun, returning whether the request was accepted."""
        if not self.enabled:
            return False
        now = time.monotonic()
        async with self._scheduler_lock:
            if trigger is ReconciliationTrigger.DEMAND:
                if (
                    self._last_expedited_at is not None
                    and now - self._last_expedited_at < self.expedited_min_interval_sec
                ):
                    return False
                self._last_expedited_at = now
            self._pending = (trigger, requested_model)
            self._wake.set()
        return True

    async def _scheduler_loop(self) -> None:
        first_wait = True
        while True:
            delay = self.startup_delay_sec if first_wait else self.interval_sec
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                async with self._scheduler_lock:
                    if self._pending is None:
                        trigger = ReconciliationTrigger.STARTUP if first_wait else ReconciliationTrigger.SCHEDULED
                        self._pending = (trigger, None)
            first_wait = False

            while True:
                async with self._scheduler_lock:
                    pending = self._pending
                    self._pending = None
                    if pending is None:
                        self._active = False
                        self._wake.clear()
                        break
                    self._active = True
                await self._run_bounded(*pending)

    async def _run_bounded(
        self,
        trigger: ReconciliationTrigger,
        requested_model: str | None,
    ) -> None:
        try:
            result = await asyncio.wait_for(
                self.run(trigger, requested_model),
                timeout=self.timeout_sec,
            )
            if isinstance(result, ReconciliationResult):
                self.last_result = result
        except asyncio.TimeoutError:
            now = datetime.now(timezone.utc)
            self.last_result = ReconciliationResult(
                outcome="failed",
                phase="timeout",
                trigger=trigger,
                requested_model=requested_model,
                counts={
                    "discovered": 0,
                    "added": 0,
                    "updated": 0,
                    "enabled": 0,
                    "disabled": 0,
                    "unchanged": 0,
                },
                verification="not_run",
                started_at=now,
                completed_at=now,
                errors=[
                    {
                        "code": "timeout",
                        "message": f"reconciliation exceeded {self.timeout_sec:g} seconds",
                        "phase": "timeout",
                    }
                ],
            )

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
        persisted_count = 0

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
                persisted_count=persisted_count,
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
            for model_id in additions:
                merged_by_id[model_id] = merged_by_id[model_id].model_copy(
                    update={"enabled": False, "status": "PENDING"}
                )
            probed_ids: set[str] = set()
            for model_id, model in list(merged_by_id.items()):
                if model_id in additions or self._probe_is_stale(model):
                    probed = await _resolve(self._probe_model(model))
                    if model_id in additions:
                        probe_succeeded = str(probed.probe_status or "").lower() == "healthy"
                        probed = probed.model_copy(update={"enabled": probe_succeeded})
                    merged_by_id[model_id] = probed
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

            phase = "persist"
            persisted_count = int(await _resolve(self._upsert_models(result_models)) or 0)
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
        except asyncio.CancelledError:
            # A scheduler timeout cancels this coroutine.  If cancellation lands
            # after apply, restore the previous artifacts before propagating it;
            # otherwise asyncio.wait_for() could report a timeout while leaving
            # an unverified configuration active.
            if rollback_token is not None:
                try:
                    async with asyncio.timeout(self.timeout_sec):
                        await _resolve(self._rollback(rollback_token))
                        await _resolve(self._reload())
                except Exception:
                    pass
            raise
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
