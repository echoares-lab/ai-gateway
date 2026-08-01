"""Guarded, read-only adapter for unified configuration snapshots."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Mapping

from api.config_snapshot import SnapshotInputs, build_config_snapshot
from core.admin_shared import resolve_gateway_admin_key
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}
_SCOPE = "config:read"
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024
_TOTAL_TIMEOUT_SECONDS = 5.0
_SOURCE_TIMEOUT_SECONDS = 2.0
_FLAG_NAMES = ("UNIFIED_CONFIG_ADMIN_API_ENABLED", "GATEWAY_ENGINE_UNIFIED_CONFIG_ADMIN_API_ENABLED")
_deps: UnifiedConfigAdminDeps | None = None

log = logging.getLogger("gateway-engine.config-snapshot")


@dataclass(frozen=True)
class UnifiedConfigAdminDeps:
    load_litellm_text: Callable[[], str]
    load_registry_model_ids: Callable[[], tuple[str, ...]]
    fetch_runtime_model_ids: Callable[[], Awaitable[tuple[str, ...]]]
    environment: Callable[[], Mapping[str, str]]
    now: Callable[[], datetime]


def configure_unified_config_admin(deps: UnifiedConfigAdminDeps) -> None:
    global _deps
    _deps = deps


def _enabled() -> bool:
    for name in _FLAG_NAMES:
        raw = os.environ.get(name)
        if raw is not None:
            return raw.strip().lower() not in {"", "0", "false", "no", "off"}
    return False


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}},
        status_code=status_code,
        headers=_NO_STORE,
    )


def _safe_log(request: Request, outcome: str, source_errors: tuple[tuple[str, str], ...] = ()) -> None:
    request_id = getattr(request.state, "req_id", "-")
    source_ids = ",".join(sorted(source for source, _code in source_errors)) or "none"
    log.info(
        "operation=config_snapshot outcome=%s request_id=%s source_ids=%s source_error_count=%d",
        outcome,
        request_id,
        source_ids,
        len(source_errors),
    )


def _source_error(source: str, code: str) -> tuple[str, str]:
    return source, code


def _ascii_key(value: str) -> bytes | None:
    try:
        return value.encode("ascii")
    except UnicodeEncodeError:
        return None


async def _load_litellm_source(deps: UnifiedConfigAdminDeps) -> tuple[str | None, str, str | None]:
    try:
        litellm_yaml = await asyncio.wait_for(
            asyncio.to_thread(deps.load_litellm_text),
            timeout=_SOURCE_TIMEOUT_SECONDS,
        )
        if not isinstance(litellm_yaml, str) or len(litellm_yaml.encode("utf-8")) > _MAX_SOURCE_BYTES:
            return None, "invalid", "source_invalid"
        return litellm_yaml, "ok", None
    except FileNotFoundError:
        return None, "missing", "source_missing"
    except (UnicodeError, ValueError):
        return None, "invalid", "source_invalid"
    except (TimeoutError, asyncio.TimeoutError):
        return None, "unavailable", "source_timeout"
    except Exception:
        return None, "unavailable", "source_unavailable"


async def _load_registry_source(
    deps: UnifiedConfigAdminDeps,
) -> tuple[tuple[str, ...] | None, str, str | None]:
    try:
        model_ids = await asyncio.wait_for(
            asyncio.to_thread(deps.load_registry_model_ids),
            timeout=_SOURCE_TIMEOUT_SECONDS,
        )
        return tuple(model_ids), "ok", None
    except (TimeoutError, asyncio.TimeoutError):
        return None, "unavailable", "source_timeout"
    except Exception:
        return None, "unavailable", "source_unavailable"


async def _load_runtime_source(
    deps: UnifiedConfigAdminDeps,
) -> tuple[tuple[str, ...] | None, str, str | None]:
    try:
        model_ids = await asyncio.wait_for(
            deps.fetch_runtime_model_ids(),
            timeout=_TOTAL_TIMEOUT_SECONDS,
        )
        return tuple(model_ids), "ok", None
    except (TimeoutError, asyncio.TimeoutError):
        return None, "unavailable", "source_timeout"
    except Exception:
        return None, "unavailable", "source_unavailable"


@router.get("/admin/config")
async def get_unified_config(request: Request) -> Response:
    if not _enabled():
        return _error("config_snapshot_disabled", "Configuration snapshot is disabled", 404)

    configured_key = resolve_gateway_admin_key()
    if not configured_key:
        return _error("config_snapshot_unavailable", "Configuration snapshot is unavailable", 503)
    configured_key_bytes = _ascii_key(configured_key)
    if configured_key_bytes is None:
        return _error("config_snapshot_unavailable", "Configuration snapshot is unavailable", 503)
    supplied_key = request.headers.get("x-admin-key", "")
    supplied_key_bytes = _ascii_key(supplied_key)
    if (
        not supplied_key
        or supplied_key_bytes is None
        or not hmac.compare_digest(supplied_key_bytes, configured_key_bytes)
    ):
        return _error("config_snapshot_auth_required", "Configuration snapshot authentication required", 401)
    if request.headers.get("x-management-scope", "") != _SCOPE:
        return _error("config_snapshot_scope_forbidden", "Configuration snapshot scope is not permitted", 403)
    if request.query_params:
        return _error("config_snapshot_invalid_request", "Configuration snapshot request is invalid", 400)

    deps = _deps
    if deps is None:
        return _error("config_snapshot_unavailable", "Configuration snapshot is unavailable", 503)

    source_errors: list[tuple[str, str]] = []
    try:
        litellm_task = asyncio.create_task(_load_litellm_source(deps))
        registry_task = asyncio.create_task(_load_registry_source(deps))
        runtime_task = asyncio.create_task(_load_runtime_source(deps))
        tasks = (litellm_task, registry_task, runtime_task)
        done, pending = await asyncio.wait(tasks, timeout=_TOTAL_TIMEOUT_SECONDS)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        litellm_yaml, litellm_status, litellm_error = (
            litellm_task.result() if litellm_task in done else (None, "unavailable", "source_timeout")
        )
        registry_model_ids, registry_status, registry_error = (
            registry_task.result() if registry_task in done else (None, "unavailable", "source_timeout")
        )
        runtime_model_ids, runtime_status, runtime_error = (
            runtime_task.result() if runtime_task in done else (None, "unavailable", "source_timeout")
        )
        for source, code in (
            ("litellm-config", litellm_error),
            ("model-registry", registry_error),
            ("runtime-visible-models", runtime_error),
        ):
            if code is not None:
                source_errors.append(_source_error(source, code))

        environment = dict(deps.environment())
        generated_at = deps.now()
        snapshot = build_config_snapshot(
            SnapshotInputs(
                litellm_yaml=litellm_yaml,
                litellm_status=litellm_status,
                registry_model_ids=registry_model_ids,
                registry_status=registry_status,
                runtime_model_ids=runtime_model_ids,
                runtime_status=runtime_status,
                environment=environment,
                generated_at=generated_at,
                source_errors=tuple(source_errors),
            )
        )
        serialized = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    except Exception:
        _safe_log(request, "unavailable", tuple(source_errors))
        return _error("config_snapshot_unavailable", "Configuration snapshot is unavailable", 503)

    if len(serialized) > _MAX_RESPONSE_BYTES:
        _safe_log(request, "too_large", tuple(source_errors))
        return _error("config_snapshot_too_large", "Configuration snapshot is too large", 502)

    outcome = "degraded" if snapshot.get("status") == "degraded" else "ok"
    _safe_log(request, outcome, tuple(source_errors))
    return Response(content=serialized, media_type="application/json", headers=_NO_STORE)
