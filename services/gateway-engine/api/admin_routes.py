"""Admin HTTP routes, deps, and re-exports for main.py."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
import yaml
from api.admin_credential_sync import (  # noqa: F401
    _credential_sync_lock,
    _credential_sync_scheduler_loop,
    _emit_credential_transition_to_policy,
    _run_scheduled_credential_sync,
    _sync_credentials_from_cliproxy,
)
from api.admin_panels import (  # noqa: F401
    _PROVIDER_LABELS,
    _PROVIDER_MODEL_SCOPE,
    _QUOTA_STATUS_HIDDEN_PROVIDERS,
    ADMIN_ERROR_MAXLEN,
    ADMIN_SCHEMA_VERSION,
    CLIPROXY_MANAGEMENT_KEY,
    CLIPROXY_URL,
    GEMINI_MODEL_MAP_PATH,
    LITELLM_CONFIG_PATH,
    MODEL_PROBE_TIMEOUT,
    _admin_config_drift_panel,
    _admin_environment,
    _admin_error,
    _admin_fetch_metrics_text,
    _admin_fetch_visible_models,
    _admin_health_panel,
    _admin_load_litellm_config,
    _admin_models_panel,
    _admin_now_iso,
    _admin_parse_provider_metrics,
    _admin_policy_engine_connectivity,
    _admin_providers_panel,
    _admin_redact,
    _admin_routing_panel,
    _admin_run_readonly_command,
    _admin_token_analytics_panel,
    _build_admin_policy_engine_data,
    _credential_inventory_store,
    _fetch_cliproxy_auth_files,
    _fetch_cliproxy_models_for_registry,
    _fetch_cliproxy_quota_status,
    _fetch_cliproxy_quota_status_full,
    _live_status_from_full,
    _load_model_registry_with_config_fallback,
    _model_registry_store,
    _nullify_sentinel_reset,
    _probe_model_via_litellm,
    _read_text_file_for_reconcile,
    _record_policy_trace,
    _redact_credential_record,
    _redact_credential_records,
    _redact_policy_decision_for_admin,
)
from core.admin_shared import _require_admin_key, _require_admin_read_access
from core.credential_inventory import (
    CredentialInventoryListResponse,
    CredentialInventorySyncRequest,
    CredentialInventorySyncResponse,
    CredentialProbeResponse,
)
from core.model_reconciliation import ModelReconciliationService, ReconciliationTrigger
from core.model_registry import (
    ModelProbeResponse,
    ModelRegistryListResponse,
    ModelRegistryMutationResponse,
    ModelRegistryPatchRequest,
    ModelRegistryReconcileRequest,
    ModelRegistryReconcileResponse,
    ModelRegistrySyncRequest,
    ModelRegistrySyncResponse,
    ModelRegistryWriteRequest,
    build_reconcile_resources,
    diff_discovered_models,
    load_models_from_litellm_config,
    merge_discovered_model,
    record_from_cliproxy_model,
)
from core.policy.schemas import CredentialEvent
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("gateway-engine.admin_routes")

_RECONCILIATION_COUNT_KEYS = ("discovered", "added", "updated", "enabled", "disabled", "unchanged")
_RECONCILIATION_PHASES = frozenset(
    {
        "idle",
        "disabled",
        "discover",
        "merge",
        "probe",
        "render",
        "validate",
        "apply",
        "reload",
        "verify",
        "persist",
        "rollback",
        "complete",
        "timeout",
    }
)
_RECONCILIATION_OUTCOMES = frozenset({"success", "degraded", "failed"})


@dataclass(frozen=True)
class AdminRouteDeps:
    get_http_client: Callable[[], httpx.AsyncClient | None]
    get_redis: Callable[[], Any | None]
    provider_of: Callable[[str], str]
    process_credential_event: Callable[[CredentialEvent], Awaitable[bool]]
    admin_policy_trace_enabled: Callable[[], bool]
    policy_engine_enabled: Callable[[], bool]
    policy_engine_ws_evaluate_enabled: Callable[[], bool]
    codex_ws_policy_bypass: Callable[[], bool]
    policy_history: list[dict]
    policy_trace: Any
    record_policy_history: Callable[..., None]
    litellm_url: str
    model_prefix: str


_default_deps: AdminRouteDeps | None = None
_policy_version_hint: str | None = None


def _admin_reconciliation_status(service: Any | None) -> dict[str, Any]:
    """Serialize bounded, secret-free reconciliation scheduler state."""
    if service is None:
        enabled = bool(_main_attr("GATEWAY_ENGINE_MODEL_RECONCILIATION_ENABLED", False))
        interval = _main_attr("GATEWAY_ENGINE_MODEL_RECONCILIATION_INTERVAL_SEC", 900)
        active = False
        pending = False
        phase = "idle" if enabled else "disabled"
        last_attempt_at = None
        last_success_at = None
        result = None
    else:
        enabled = bool(getattr(service, "enabled", False))
        interval = getattr(service, "interval_sec", 900)
        active = bool(getattr(service, "active", False))
        pending = bool(getattr(service, "pending", False))
        phase = str(getattr(service, "phase", "idle" if enabled else "disabled"))
        last_attempt_at = getattr(service, "last_attempt_at", None)
        last_success_at = getattr(service, "last_success_at", None)
        result = getattr(service, "last_result", None)

    if phase not in _RECONCILIATION_PHASES:
        phase = "idle"
    raw_outcome = str(getattr(result, "outcome", "")) if result is not None else ""
    outcome = raw_outcome if raw_outcome in _RECONCILIATION_OUTCOMES else None
    raw_trigger = getattr(service, "current_trigger", None) if active else None
    if raw_trigger is None:
        raw_trigger = getattr(result, "trigger", None) if result is not None else None
    trigger = getattr(raw_trigger, "value", raw_trigger)
    if trigger not in {member.value for member in ReconciliationTrigger}:
        trigger = None
    requested_model = getattr(service, "current_requested_model", None) if active else None
    if requested_model is None:
        requested_model = getattr(result, "requested_model", None) if result is not None else None
    if requested_model is not None:
        requested_model = _admin_redact(str(requested_model))[0]
    counts = getattr(result, "counts", {}) if result is not None else {}
    errors = []
    for error in (getattr(result, "errors", []) if result is not None else [])[:10]:
        if not isinstance(error, dict):
            continue
        message, redacted = _admin_redact(str(error.get("message", "")))
        code = _admin_redact(str(error.get("code", "unknown")))[0]
        error_phase = _admin_redact(str(error.get("phase", "unknown")))[0]
        errors.append({"code": code, "phase": error_phase, "message": message, "redacted": redacted})

    def iso(value: Any) -> str | None:
        return (
            value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else None
        )

    return {
        "enabled": enabled,
        "interval_seconds": max(0, int(interval)),
        "active": active,
        "pending": pending,
        "phase": phase,
        "last_attempt_at": iso(last_attempt_at),
        "last_success_at": iso(last_success_at),
        "trigger": trigger,
        "requested_model": requested_model,
        "outcome": outcome,
        "counts": {key: max(0, int(counts.get(key, 0))) for key in _RECONCILIATION_COUNT_KEYS},
        "verification": str(getattr(result, "verification", "not_run")) if result is not None else "not_run",
        "errors": errors,
    }


def _main_attr(name: str, default):
    main_module = sys.modules.get("main")
    return getattr(main_module, name, default) if main_module is not None else default


def _deps() -> AdminRouteDeps:
    if _default_deps is None:
        raise RuntimeError("admin routes dependencies not configured")
    return _default_deps


def configure_admin_routes(deps: AdminRouteDeps) -> None:
    global _default_deps
    _default_deps = deps


router = APIRouter()


@router.get("/admin/analytics/tokens")
async def admin_token_analytics(request: Request):
    """Granular token usage analytics by provider and model (#117)."""
    auth_error = _require_admin_read_access(request)
    if auth_error is not None:
        return auth_error
    metrics_text, errors = await _admin_fetch_metrics_text()
    return _admin_token_analytics_panel(metrics_text, errors)


@router.get("/admin/credentials", response_model=CredentialInventoryListResponse)
async def admin_credentials(request: Request):
    """List redacted gateway-engine credential inventory records."""
    auth_error = _require_admin_read_access(request)
    if auth_error is not None:
        return auth_error
    loaded = _credential_inventory_store().list_credentials()
    return loaded.model_copy(update={"credentials": _redact_credential_records(loaded.credentials)})


@router.post("/admin/credentials/sync", response_model=CredentialInventorySyncResponse)
async def admin_credentials_sync(request: Request, body: CredentialInventorySyncRequest):
    """Sync CLIProxy auth-file state into credential_inventory."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error
    return await _sync_credentials_from_cliproxy(body)


@router.get("/admin/quota/status")
async def admin_quota_status(request: Request):
    """Real-time OAuth quota status aggregated from CLIProxy, with full per-window breakdown."""
    auth_error = _require_admin_read_access(request)
    if auth_error is not None:
        return auth_error

    (quota_creds, quota_errors), (full_creds, full_errors), (auth_files, auth_errors) = await asyncio.gather(
        _fetch_cliproxy_quota_status(),
        _fetch_cliproxy_quota_status_full(),
        _fetch_cliproxy_auth_files(),
    )

    all_errors = quota_errors + full_errors + auth_errors
    if all_errors and not quota_creds:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "errors": all_errors},
        )

    # Lookups keyed by credential id
    auth_by_id: dict[str, dict] = {f["id"]: f for f in auth_files if "id" in f}
    full_by_id: dict[str, dict] = {c["id"]: c for c in full_creds if "id" in c}

    accounts = []
    for cred in quota_creds:
        cred_id = cred.get("id", "")
        if not cred_id or cred.get("provider", "") in ("", "unknown"):
            continue
        provider = cred.get("provider", "")
        # Retired Gemini CLI tier + orphaned bare Gemini API-key auth files never
        # route production traffic; hide them from the display layer instead of
        # confusing operators with dead-account rows (see docs/ROADMAP.md).
        if provider in _QUOTA_STATUS_HIDDEN_PROVIDERS:
            continue
        auth = auth_by_id.get(cred_id, {})
        full = full_by_id.get(cred_id, {})

        utilization_pct_raw = cred.get("utilization_pct")
        resets_at = _nullify_sentinel_reset(cred.get("resets_at"))
        captured_at = _nullify_sentinel_reset(cred.get("captured_at"))
        resets_in = cred.get("resets_in")
        stale = bool(cred.get("stale"))
        utilization_pct = None if stale and utilization_pct_raw == 0 else utilization_pct_raw

        # Build windows from full quota data when available; fall back to binding-only
        full_windows = full.get("windows") or {}

        def _window(key: str) -> dict:
            w = full_windows.get(key)
            if w and isinstance(w, dict):
                return {
                    "utilization_pct": w.get("utilization_pct"),
                    "resets_at": _nullify_sentinel_reset(w.get("resets_at")),
                }
            return {"utilization_pct": None, "resets_at": None}

        windows: dict = {
            "five_hour": _window("five_hour"),
            "seven_day": _window("seven_day"),
        }
        # Include non-null named sub-windows (opus, sonnet, oauth_apps, etc.)
        for key, w in full_windows.items():
            if key not in ("five_hour", "seven_day") and w is not None:
                windows[key] = {
                    "utilization_pct": w.get("utilization_pct"),
                    "resets_at": _nullify_sentinel_reset(w.get("resets_at")),
                }
        # Binding constraint from passive headers (always present, even before full data arrives)
        windows["binding"] = {
            "utilization_pct": utilization_pct,
            "resets_at": resets_at,
            "resets_in": resets_in,
        }

        live_status = _live_status_from_full(full)
        quota_entry: dict = {
            "source": cred.get("quota_source", ""),
            "stale": stale,
            "captured_at": captured_at,
            "windows": windows,
            "tokens_remaining": None if stale else cred.get("tokens_remaining"),
            "tokens_limit": None if stale else cred.get("tokens_limit"),
            "requests_remaining": None if stale else cred.get("requests_remaining"),
            "requests_limit": None if stale else cred.get("requests_limit"),
            "live_status": live_status,
        }
        # fetched_at is success-only upstream; only surface on fresh live results
        if live_status == "fresh" and full.get("fetched_at"):
            quota_entry["live_fetched_at"] = full["fetched_at"]
        # Compute depletion forecasting / risk signal for high-utilization active accounts
        depletion_forecast = None
        binding_win = windows.get("binding") or {}
        bind_util = binding_win.get("utilization_pct")
        if not stale and bind_util is not None and isinstance(bind_util, (int, float)):
            if bind_util >= 85:
                depletion_forecast = {
                    "risk_level": "critical" if bind_util >= 95 else "warning",
                    "status_message": f"Account at {bind_util}% quota utilization (exhaustion risk active)",
                }
            else:
                depletion_forecast = {
                    "risk_level": "normal",
                    "status_message": f"Account utilization healthy at {bind_util}%",
                }
        quota_entry["depletion_forecast"] = depletion_forecast

        # Surface fetch error from full endpoint (non-fatal)
        if full.get("error"):
            quota_entry["full_quota_error"] = full["error"]

        accounts.append(
            {
                "credential_id": cred_id,
                "email": auth.get("email") or cred.get("label", ""),
                "provider": provider,
                "provider_label": _PROVIDER_LABELS.get(provider, provider),
                "plan_type": full.get("plan_type"),
                "account_status": "disabled" if auth.get("disabled") else auth.get("status", "unknown"),
                "disabled": bool(auth.get("disabled")),
                "applies_to_models": _PROVIDER_MODEL_SCOPE.get(provider, f"All {provider} models"),
                "quota": quota_entry,
            }
        )

    accounts.sort(key=lambda a: (a["provider"], a["email"]))

    # partial only for active (non-disabled) credentials in missing/error live states
    partial = any(
        (not account["disabled"]) and account["quota"].get("live_status") in ("missing", "error")
        for account in accounts
    )

    return JSONResponse(
        content={
            "status": "ok",
            "source": "cliproxy:/v0/management/quota-status + /quota-status/full",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "partial": partial,
            "accounts": accounts,
            **({"errors": all_errors} if all_errors else {}),
        }
    )


@router.post("/admin/credentials/{credential_id}/probe", response_model=CredentialProbeResponse)
async def admin_credential_probe(credential_id: str, request: Request):
    """Targeted credential probing is reserved until CLIProxy exposes a probe API."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error
    return JSONResponse(
        CredentialProbeResponse(
            credential_id=credential_id,
            errors=[
                _admin_error(
                    "targeted_probe_unsupported",
                    "CLIProxy management API does not expose targeted credential probe",
                    "cliproxy:/v0/management",
                )
            ],
        ).model_dump(mode="json"),
        status_code=501,
    )


@router.get("/admin/models", response_model=ModelRegistryListResponse)
async def admin_models(request: Request):
    auth_error = _require_admin_read_access(request)
    if auth_error is not None:
        return auth_error
    """List gateway-engine-owned model registry records, falling back to LiteLLM config."""
    return _load_model_registry_with_config_fallback()


@router.post("/admin/models", response_model=ModelRegistryMutationResponse)
async def admin_model_create(request: Request, body: ModelRegistryWriteRequest):
    """Create or replace one model registry record."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error
    store = _model_registry_store()
    if not store.enabled:
        return ModelRegistryMutationResponse(
            accepted=False,
            registry_available=False,
            errors=[
                _admin_error(
                    "registry_unavailable",
                    "DATABASE_URL or psycopg2 unavailable",
                    "postgres:model_registry",
                )
            ],
        )
    try:
        model = store.upsert_model(body.to_record())
    except Exception as exc:
        return ModelRegistryMutationResponse(
            accepted=False,
            registry_available=store.enabled,
            errors=[
                _admin_error(
                    "registry_write_error",
                    f"{type(exc).__name__}: {exc}",
                    "postgres:model_registry",
                )
            ],
        )
    return ModelRegistryMutationResponse(registry_available=True, model=model)


@router.get("/admin/models/{model_id}", response_model=ModelRegistryListResponse)
async def admin_model(model_id: str, request: Request):
    auth_error = _require_admin_read_access(request)
    if auth_error is not None:
        return auth_error
    """Read one model registry record by id, with config fallback."""
    loaded = _load_model_registry_with_config_fallback()
    matches = [model for model in loaded.models if model.model_id == model_id]
    if not matches:
        return JSONResponse(
            {
                "source": loaded.source,
                "registry_available": loaded.registry_available,
                "models": [],
                "errors": loaded.errors,
            },
            status_code=404,
        )
    return ModelRegistryListResponse(
        source=loaded.source,
        registry_available=loaded.registry_available,
        models=matches,
        errors=loaded.errors,
    )


@router.patch("/admin/models/{model_id}", response_model=ModelRegistryMutationResponse)
async def admin_model_patch(
    model_id: str,
    request: Request,
    body: ModelRegistryPatchRequest,
):
    """Patch one model registry record."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error
    store = _model_registry_store()
    current = store.get_model(model_id)
    if current is None:
        return JSONResponse(
            {
                "accepted": False,
                "registry_available": store.enabled,
                "model": None,
                "errors": [
                    _admin_error(
                        "model_not_found",
                        f"{model_id} not found",
                        "postgres:model_registry",
                    )
                ],
            },
            status_code=404,
        )
    try:
        model = store.upsert_model(body.apply(current))
    except Exception as exc:
        return ModelRegistryMutationResponse(
            accepted=False,
            registry_available=store.enabled,
            errors=[
                _admin_error(
                    "registry_write_error",
                    f"{type(exc).__name__}: {exc}",
                    "postgres:model_registry",
                )
            ],
        )
    return ModelRegistryMutationResponse(registry_available=store.enabled, model=model)


@router.delete("/admin/models/{model_id}", response_model=ModelRegistryMutationResponse)
async def admin_model_delete(model_id: str, request: Request, hard: bool = False):
    """Disable one model by default; hard delete only when hard=true."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error
    store = _model_registry_store()
    try:
        if hard:
            deleted = store.hard_delete_model(model_id)
            if not deleted:
                return JSONResponse(
                    {
                        "accepted": False,
                        "registry_available": store.enabled,
                        "model": None,
                        "errors": [
                            _admin_error(
                                "model_not_found",
                                f"{model_id} not found",
                                "postgres:model_registry",
                            )
                        ],
                    },
                    status_code=404,
                )
            return ModelRegistryMutationResponse(registry_available=store.enabled)
        model = store.disable_model(model_id)
    except Exception as exc:
        return ModelRegistryMutationResponse(
            accepted=False,
            registry_available=store.enabled,
            errors=[
                _admin_error(
                    "registry_write_error",
                    f"{type(exc).__name__}: {exc}",
                    "postgres:model_registry",
                )
            ],
        )
    if model is None:
        return JSONResponse(
            {
                "accepted": False,
                "registry_available": store.enabled,
                "model": None,
                "errors": [
                    _admin_error(
                        "model_not_found",
                        f"{model_id} not found",
                        "postgres:model_registry",
                    )
                ],
            },
            status_code=404,
        )
    return ModelRegistryMutationResponse(registry_available=store.enabled, model=model)


@router.post("/admin/models/{model_id}/probe", response_model=ModelProbeResponse)
async def admin_model_probe(model_id: str, request: Request):
    """Probe one model through LiteLLM and persist the normalized probe result."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error

    store = _model_registry_store()
    current = store.get_model(model_id)
    if current is None:
        return JSONResponse(
            {
                "accepted": False,
                "registry_available": store.enabled,
                "model_id": model_id,
                "probe_status": "missing_model",
                "probe_http_status": None,
                "probe_checked_at": datetime.now(timezone.utc).isoformat(),
                "model": None,
                "errors": [
                    _admin_error(
                        "model_not_found",
                        f"{model_id} not found",
                        "postgres:model_registry",
                    )
                ],
            },
            status_code=404,
        )

    probe_status, probe_http_status, errors = await _probe_model_via_litellm(model_id)
    checked_at = datetime.now(timezone.utc)
    try:
        model = store.update_probe_result(
            model_id,
            probe_status=probe_status,
            probe_http_status=probe_http_status,
            probe_checked_at=checked_at,
        )
    except Exception as exc:
        return ModelProbeResponse(
            accepted=False,
            registry_available=store.enabled,
            model_id=model_id,
            probe_status=probe_status,
            probe_http_status=probe_http_status,
            probe_checked_at=checked_at,
            model=current,
            errors=[
                *errors,
                _admin_error(
                    "registry_write_error",
                    f"{type(exc).__name__}: {exc}",
                    "postgres:model_registry",
                ),
            ],
        )

    return ModelProbeResponse(
        registry_available=store.enabled,
        model_id=model_id,
        probe_status=probe_status,
        probe_http_status=probe_http_status,
        probe_checked_at=checked_at,
        model=model or current,
        errors=errors,
    )


@router.post("/admin/models/reconcile", response_model=ModelRegistryReconcileResponse)
async def admin_models_reconcile(request: Request, body: ModelRegistryReconcileRequest):
    """Render a dry run or enqueue a full reconciliation on the singleton scheduler."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error

    if not body.dry_run:
        service = _main_attr("_model_reconciliation_service", None)
        accepted = bool(service is not None and await service.request(ReconciliationTrigger.MANUAL))
        errors = (
            []
            if accepted
            else [
                _admin_error(
                    "scheduler_unavailable", "model reconciliation scheduler unavailable", "gateway-engine:scheduler"
                )
            ]
        )
        return ModelRegistryReconcileResponse(
            accepted=accepted,
            dry_run=False,
            source="scheduler:model-reconciliation",
            registry_available=bool(_main_attr("_model_registry_store", _model_registry_store)().enabled),
            resources=[],
            errors=errors,
        )

    loaded = _load_model_registry_with_config_fallback()
    litellm_text, litellm_errors = _read_text_file_for_reconcile(
        _main_attr("LITELLM_CONFIG_PATH", LITELLM_CONFIG_PATH),
        "repo:litellm-config.yaml",
    )
    gemini_text, gemini_errors = _read_text_file_for_reconcile(
        _main_attr("GEMINI_MODEL_MAP_PATH", GEMINI_MODEL_MAP_PATH),
        "repo:gemini-model-map.json",
    )
    errors = [*loaded.errors, *litellm_errors, *gemini_errors]

    def render(models):
        return build_reconcile_resources(
            models,
            current_litellm_config=litellm_text,
            current_gemini_map=gemini_text,
            include_disabled=body.include_disabled,
        )

    def validate(resources):
        for resource in resources:
            (yaml.safe_load if resource.kind == "yaml" else json.loads)(resource.content)

    service = ModelReconciliationService(
        discover=lambda: loaded.models,
        list_models=lambda: loaded.models,
        upsert_models=lambda models: 0,
        probe_model=lambda model: model,
        render=render,
        validate=validate,
        apply=lambda resources: None,
        rollback=lambda token: None,
        reload=lambda: True,
        read_catalog=lambda: set(),
        probe_is_stale=lambda model: False,
    )
    result = await service.run(ReconciliationTrigger.MANUAL, dry_run=True)
    errors.extend(result.errors)
    return ModelRegistryReconcileResponse(
        dry_run=True,
        source=loaded.source,
        registry_available=loaded.registry_available,
        resources=result.resources or [],
        errors=errors,
    )


@router.post("/admin/models/sync", response_model=ModelRegistrySyncResponse)
async def admin_models_sync(request: Request, body: ModelRegistrySyncRequest):
    """Import current LiteLLM config or CLIProxy discovery into the model registry."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error

    store = _model_registry_store()
    existing = store.list_models()
    existing_models = existing.models if existing.registry_available else []
    errors = list(existing.errors)
    source = body.source

    if source == "cliproxy":
        entries, fetch_errors = await _fetch_cliproxy_models_for_registry()
        discovered = [model for model in (record_from_cliproxy_model(entry) for entry in entries) if model is not None]
        errors.extend(fetch_errors)
        diffs = diff_discovered_models(discovered, existing_models)
        loaded_models = [
            merge_discovered_model(model, {m.model_id: m for m in existing_models}.get(model.model_id))
            for model in discovered
        ]
    else:
        loaded = load_models_from_litellm_config(_main_attr("LITELLM_CONFIG_PATH", LITELLM_CONFIG_PATH))
        errors.extend(loaded.errors)
        loaded_models = loaded.models
        diffs = diff_discovered_models(loaded_models, existing_models)

    imported = 0
    if not errors or body.dry_run:

        async def probe_model(model):
            probe_status, probe_http_status, _probe_errors = await _main_attr(
                "_probe_model_via_litellm", _probe_model_via_litellm
            )(model.model_id)
            healthy = probe_status == "success"
            return model.model_copy(
                update={
                    "probe_status": "healthy" if healthy else probe_status,
                    "probe_http_status": probe_http_status,
                    "probe_checked_at": datetime.now(timezone.utc),
                    "status": "HEALTHY" if healthy else "UNHEALTHY",
                }
            )

        service = ModelReconciliationService(
            discover=lambda: loaded_models,
            list_models=lambda: existing_models,
            upsert_models=store.upsert_models,
            probe_model=(lambda model: model) if body.dry_run else probe_model,
            render=lambda models: [],
            validate=lambda resources: True,
            apply=lambda resources: None,
            rollback=lambda token: None,
            reload=lambda: True,
            read_catalog=lambda: {model.model_id for model in loaded_models if model.enabled},
            probe_is_stale=lambda model: False,
        )
        result = await service.run(ReconciliationTrigger.MANUAL, dry_run=body.dry_run)
        loaded_models = result.models
        diffs = result.diffs
        errors.extend(result.errors)
        if result.outcome == "success":
            imported = len(loaded_models) if body.dry_run else result.persisted_count
    return ModelRegistrySyncResponse(
        dry_run=body.dry_run,
        source=source,
        registry_available=store.enabled,
        imported_count=imported,
        skipped_count=max(0, len(loaded_models) - imported),
        models=loaded_models,
        diffs=diffs,
        errors=errors,
    )


@router.get("/admin/status")
async def admin_status(request: Request):
    """Read-only operator status aggregator (admin-console.v1)."""
    auth_error = _require_admin_read_access(request)
    if auth_error is not None:
        return auth_error
    config, config_errors = _main_attr("_admin_load_litellm_config", _admin_load_litellm_config)()
    registry = _main_attr("_load_model_registry_with_config_fallback", _load_model_registry_with_config_fallback)()
    visible_ids, model_errors = await _main_attr("_admin_fetch_visible_models", _admin_fetch_visible_models)()
    metrics_text, metrics_errors = await _main_attr("_admin_fetch_metrics_text", _admin_fetch_metrics_text)()
    redis_ok, policy_version = await _main_attr(
        "_admin_policy_engine_connectivity",
        _admin_policy_engine_connectivity,
    )()
    policy_engine = _main_attr("_build_admin_policy_engine_data", _build_admin_policy_engine_data)(
        redis_connected=redis_ok,
        policy_version=policy_version,
    )

    models_panel = _admin_models_panel(config, visible_ids, model_errors, registry)
    models_panel["reconciliation"] = _admin_reconciliation_status(_main_attr("_model_reconciliation_service", None))
    panels = {
        "health": _admin_health_panel(),
        "models": models_panel,
        "providers": _admin_providers_panel(),
        "routing": _admin_routing_panel(
            config,
            metrics_text,
            metrics_errors,
            policy_engine=policy_engine,
        ),
        "config_drift": _admin_config_drift_panel(config, config_errors),
        "token_analytics": _admin_token_analytics_panel(metrics_text, metrics_errors),
    }
    return {
        "schema_version": ADMIN_SCHEMA_VERSION,
        "generated_at": _admin_now_iso(),
        "environment": _admin_environment(),
        "panels": panels,
    }


@router.get("/admin/status/policy")
async def admin_policy_trace_history(request: Request):
    """Expose recent policy routing decisions (issue #184)."""
    auth_error = _require_admin_read_access(request)
    if auth_error is not None:
        return auth_error
    return [
        {
            **entry,
            "decision": _redact_policy_decision_for_admin(entry["decision"])
            if isinstance(entry.get("decision"), dict)
            else entry.get("decision"),
            "error": _admin_redact(entry["error"])[0] if entry.get("error") else None,
        }
        for entry in _deps().policy_history
    ]


# Self-contained operator dashboard (issue #70). Read-only: the page fetches
# /admin/status client-side and renders it. The server embeds no secrets — only
# static HTML/CSS/JS. Operator-local by convention (no public exposure added).
_ADMIN_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Gateway — Admin Console</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg-color: #0b0e14;
    --panel-bg: rgba(22, 28, 38, 0.7);
    --border-color: rgba(255, 255, 255, 0.08);
    --text-primary: #f3f4f6;
    --text-secondary: #9ca3af;
    --primary-color: #3b82f6;
    --primary-glow: rgba(59, 130, 246, 0.35);
    --ok-color: #10b981;
    --ok-glow: rgba(16, 185, 129, 0.25);
    --warning-color: #f59e0b;
    --warning-glow: rgba(245, 158, 11, 0.25);
    --error-color: #ef4444;
    --error-glow: rgba(239, 68, 68, 0.25);
  }

  body {
    font-family: 'Outfit', system-ui, sans-serif;
    margin: 0;
    padding: 2rem;
    background-color: var(--bg-color);
    color: var(--text-primary);
    line-height: 1.5;
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.5rem;
    background: var(--panel-bg);
    backdrop-filter: blur(12px);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    margin-bottom: 2rem;
    box-shadow: 0 4px 30px rgba(0, 0, 0, 0.4);
  }

  @media (max-width: 768px) {
    header {
      flex-direction: column;
      align-items: flex-start;
      gap: 1rem;
    }
  }

  .brand h1 {
    font-size: 1.5rem;
    font-weight: 600;
    margin: 0 0 0.25rem;
    background: linear-gradient(135deg, #60a5fa, #3b82f6);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }

  .brand-meta {
    font-size: 0.85rem;
    color: var(--text-secondary);
  }

  .header-controls {
    display: flex;
    align-items: center;
    gap: 1.5rem;
    width: 100%;
    justify-content: flex-end;
  }

  @media (max-width: 768px) {
    .header-controls {
      justify-content: space-between;
    }
  }

  .links {
    display: flex;
    gap: 0.75rem;
  }

  .links a {
    color: #60a5fa;
    text-decoration: none;
    font-size: 0.875rem;
    font-weight: 500;
    padding: 0.4rem 0.8rem;
    border-radius: 6px;
    background: rgba(96, 165, 250, 0.1);
    border: 1px solid rgba(96, 165, 250, 0.2);
    transition: all 0.2s ease;
  }

  .links a:hover {
    background: rgba(96, 165, 250, 0.2);
    border-color: rgba(96, 165, 250, 0.4);
    transform: translateY(-1px);
  }

  .refresh-btn {
    background: var(--primary-color);
    color: #fff;
    border: none;
    font-size: 0.875rem;
    font-weight: 600;
    padding: 0.5rem 1.2rem;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
    box-shadow: 0 0 12px var(--primary-glow);
  }

  .refresh-btn:hover {
    background: #2563eb;
    transform: translateY(-1px);
    box-shadow: 0 0 18px var(--primary-glow);
  }

  .refresh-btn:active {
    transform: translateY(1px);
  }

  /* Tabs */
  .tabs {
    display: flex;
    gap: 1rem;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 0.5rem;
  }

  .tab-btn {
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 1rem;
    font-weight: 600;
    padding: 0.5rem 1rem;
    cursor: pointer;
    transition: all 0.2s ease;
    position: relative;
  }

  .tab-btn:hover {
    color: var(--text-primary);
  }

  .tab-btn.active {
    color: var(--primary-color);
  }

  .tab-btn.active::after {
    content: '';
    position: absolute;
    bottom: -0.6rem;
    left: 0;
    width: 100%;
    height: 3px;
    background: var(--primary-color);
    border-radius: 2px;
    box-shadow: 0 0 8px var(--primary-color);
  }

  /* Stat Cards */
  .stats-container {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1.5rem;
    margin-bottom: 2rem;
  }

  .stat-card {
    background: var(--panel-bg);
    backdrop-filter: blur(12px);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
    position: relative;
    overflow: hidden;
  }

  .stat-card::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    width: 4px;
    height: 100%;
    background: var(--primary-color);
  }

  .stat-card.cached::before {
    background: var(--ok-color);
  }

  .stat-card.non-cached::before {
    background: var(--warning-color);
  }

  .stat-title {
    font-size: 0.875rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 0.5rem;
  }

  .stat-value {
    font-size: 2rem;
    font-weight: 700;
    margin-bottom: 0.5rem;
    font-feature-settings: "tnum";
  }

  .stat-sub {
    font-size: 0.85rem;
    color: var(--text-secondary);
  }

  /* Progress bar */
  .progress-container {
    width: 100%;
    height: 6px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 999px;
    margin-top: 0.75rem;
    overflow: hidden;
  }

  .progress-bar {
    height: 100%;
    background: var(--primary-color);
    border-radius: 999px;
    transition: width 0.5s ease-out;
  }

  .progress-bar.cached {
    background: var(--ok-color);
  }

  /* Grid Layout */
  .dashboard-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(480px, 1fr));
    gap: 1.5rem;
  }

  @media (max-width: 600px) {
    .dashboard-grid {
      grid-template-columns: 1fr;
    }
  }

  .panel-card {
    background: var(--panel-bg);
    backdrop-filter: blur(12px);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
  }

  .panel-card h2 {
    font-size: 1.2rem;
    font-weight: 600;
    margin-top: 0;
    margin-bottom: 1.25rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  /* Badges */
  .badge {
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.25rem 0.75rem;
    border-radius: 999px;
    text-transform: uppercase;
  }

  .badge.ok {
    background: rgba(16, 185, 129, 0.15);
    color: var(--ok-color);
    border: 1px solid rgba(16, 185, 129, 0.3);
    box-shadow: 0 0 10px rgba(16, 185, 129, 0.1);
  }

  .badge.warning {
    background: rgba(245, 158, 11, 0.15);
    color: var(--warning-color);
    border: 1px solid rgba(245, 158, 11, 0.3);
  }

  .badge.error {
    background: rgba(239, 68, 68, 0.15);
    color: var(--error-color);
    border: 1px solid rgba(239, 68, 68, 0.3);
    box-shadow: 0 0 10px rgba(239, 68, 68, 0.1);
  }

  .badge.unknown {
    background: rgba(176, 182, 191, 0.15);
    color: var(--text-secondary);
    border: 1px solid rgba(176, 182, 191, 0.3);
  }

  /* Lists and Tables */
  .item-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 0;
    border-bottom: 1px solid var(--border-color);
  }

  .item-row:last-child {
    border-bottom: none;
  }

  .item-label {
    font-weight: 500;
  }

  .item-value {
    font-weight: 600;
    font-feature-settings: "tnum";
  }

  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 0.5rem;
  }

  th, td {
    text-align: left;
    padding: 0.75rem 0.5rem;
    border-bottom: 1px solid var(--border-color);
  }

  th {
    font-size: 0.8rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
  }

  td {
    font-size: 0.9rem;
  }

  .table-progress {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .table-progress-bar {
    width: 60px;
    height: 6px;
    background: rgba(255, 255, 255, 0.1);
    border-radius: 999px;
    overflow: hidden;
  }

  .table-progress-fill {
    height: 100%;
    background: var(--ok-color);
  }

  /* Raw Panels View */
  .raw-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
    gap: 1.5rem;
  }

  .raw-panel {
    background: var(--panel-bg);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 1.25rem;
  }

  .raw-panel h2 {
    font-size: 1rem;
    margin: 0 0 0.75rem;
    text-transform: capitalize;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  pre {
    background: rgba(10, 12, 16, 0.75);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 1rem;
    font-family: monospace;
    font-size: 0.8rem;
    color: #c8cdd4;
    overflow: auto;
    max-height: 20rem;
    margin: 0;
  }

  .err {
    color: var(--error-color);
    font-size: 0.85rem;
    margin-top: 0.5rem;
  }

  .hidden {
    display: none !important;
  }
</style>
</head>
<body>
  <header>
    <div class="brand">
      <h1>AI Gateway — Admin Console</h1>
      <div class="brand-meta">
        Schema: <span id="schema">…</span> | Generated: <span id="generated">…</span>
      </div>
    </div>
    <div class="header-controls">
      <div class="links" id="links"></div>
      <button class="refresh-btn" onclick="load()">Refresh</button>
    </div>
  </header>

  <div class="tabs">
    <button id="tab-overview" class="tab-btn active" onclick="switchTab('overview')">Overview Dashboard</button>
    <button id="tab-raw" class="tab-btn" onclick="switchTab('raw')">Raw Metrics Panels</button>
  </div>

  <div id="overview-content">
    <div class="stats-container">
      <div class="stat-card">
        <div class="stat-title">Total Processed Tokens</div>
        <div class="stat-value" id="stat-total-tokens">0</div>
        <div class="stat-sub" id="stat-total-detail">0 input / 0 output</div>
      </div>
      <div class="stat-card cached">
        <div class="stat-title">Cached Tokens</div>
        <div class="stat-value" id="stat-cached-tokens">0</div>
        <div class="stat-sub" id="stat-cached-ratio">0% overall cache hit ratio</div>
        <div class="progress-container">
          <div class="progress-bar cached" id="bar-cached-ratio" style="width: 0%"></div>
        </div>
      </div>
      <div class="stat-card non-cached">
        <div class="stat-title">Non-Cached (Upstream Billed)</div>
        <div class="stat-value" id="stat-upstream-tokens">0</div>
        <div class="stat-sub" id="stat-upstream-ratio">0% hit the provider directly</div>
        <div class="progress-container">
          <div class="progress-bar" id="bar-upstream-ratio" style="width: 0%; background: var(--warning-color)"></div>
        </div>
      </div>
    </div>

    <div class="dashboard-grid">
      <!-- Health & Systems -->
      <div class="panel-card" id="card-health">
        <h2>System Health <span id="badge-health" class="badge">…</span></h2>
        <div id="health-details"></div>
      </div>

      <!-- Cache Type Breakdown -->
      <div class="panel-card" id="card-cache-types">
        <h2>Caching Types Breakdown</h2>
        <div id="cache-types-details">
          <table>
            <thead>
              <tr>
                <th>Cache Tier</th>
                <th>Input Tokens</th>
                <th>Output Tokens</th>
                <th>Total Tokens</th>
              </tr>
            </thead>
            <tbody id="cache-types-table-body">
              <tr><td colspan="4" style="text-align: center; color: var(--text-secondary)">No cache analytics available</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Top Models -->
      <div class="panel-card" id="card-models" style="grid-column: span 2">
        <h2>Active Models Performance</h2>
        <div style="overflow-x: auto;">
          <table>
            <thead>
              <tr>
                <th>Model ID</th>
                <th>Provider</th>
                <th>Total Tokens</th>
                <th>Cached Tokens</th>
                <th>Cache Ratio</th>
              </tr>
            </thead>
            <tbody id="models-table-body">
              <tr><td colspan="5" style="text-align: center; color: var(--text-secondary)">Loading model stats…</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Top Providers -->
      <div class="panel-card" id="card-providers">
        <h2>Providers Performance</h2>
        <div style="overflow-x: auto;">
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Models</th>
                <th>Total Tokens</th>
                <th>Cached Ratio</th>
              </tr>
            </thead>
            <tbody id="providers-table-body">
              <tr><td colspan="4" style="text-align: center; color: var(--text-secondary)">Loading provider stats…</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Configuration Drift & Policy -->
      <div class="panel-card" id="card-config">
        <h2>Configuration & Policies</h2>
        <div id="config-details"></div>
      </div>
    </div>
  </div>

  <div id="raw-content" class="hidden">
    <div id="raw-grid" class="raw-grid"><div class="brand-meta">Loading raw panels…</div></div>
  </div>

<script>
let currentTab = 'overview';
let activeData = null;

function badge(s) {
  const c = ['ok', 'warning', 'error', 'unknown'].includes(s) ? s : 'unknown';
  return '<span class="badge ' + c + '">' + (s || 'unknown') + '</span>';
}

function esc(v) {
  return JSON.stringify(v, null, 2)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatNum(n) {
  if (n === null || n === undefined) return '-';
  return n.toLocaleString();
}

function switchTab(tab) {
  currentTab = tab;
  document.getElementById('tab-overview').classList.toggle('active', tab === 'overview');
  document.getElementById('tab-raw').classList.toggle('active', tab === 'raw');
  document.getElementById('overview-content').classList.toggle('hidden', tab !== 'overview');
  document.getElementById('raw-content').classList.toggle('hidden', tab === 'overview');
  if (activeData) render(activeData);
}

async function load() {
  const grid = document.getElementById('raw-grid');
  try {
    const r = await fetch('/admin/status', { headers: { 'accept': 'application/json' } });
    const d = await r.json();
    activeData = d;
    render(d);
  } catch (e) {
    grid.innerHTML = '<div class="err">Failed to load /admin/status: ' + e + '</div>';
  }
}

function render(d) {
  // Update Header Metadata
  document.getElementById('schema').textContent = d.schema_version || '';
  document.getElementById('generated').textContent = d.generated_at || '';

  // Render Environment Links
  const env = d.environment || {};
  document.getElementById('links').innerHTML = [
    ['LiteLLM UI', env.litellm_ui_url],
    ['CLIProxy', env.cliproxy_management_url],
    ['CPA-Manager', env.cpa_manager_url],
  ].filter(x => x[1]).map(x => '<a href="' + x[1] + '" target="_blank" rel="noopener">'+x[0]+'</a>').join('');

  const panels = d.panels || {};

  // RENDER OVERVIEW VISUALS
  renderStats(panels.token_analytics);
  renderHealth(panels.health);
  renderCacheBreakdown(panels.token_analytics);
  renderModelsTable(panels.token_analytics);
  renderProvidersTable(panels.token_analytics);
  renderConfigDetails(panels.config_drift, panels.routing);

  // RENDER RAW VIEW
  const rawGrid = document.getElementById('raw-grid');
  rawGrid.innerHTML = Object.keys(panels).map(function(name) {
    const p = panels[name] || {};
    const errs = (p.errors || []).map(e => '<div class="err">' + (e.code || '') + ': ' + (e.message || '') + '</div>').join('');
    return '<div class="raw-panel"><h2>' + name + ' ' + badge(p.status) + '</h2>' + errs +
      '<pre>' + esc(p.data || {}) + '</pre></div>';
  }).join('');
}

function renderStats(ta) {
  if (!ta || !ta.data || !ta.data.summary) return;
  const s = ta.data.summary;

  document.getElementById('stat-total-tokens').textContent = formatNum(s.total_tokens || 0);
  document.getElementById('stat-total-detail').textContent =
    formatNum(s.total_input_tokens || 0) + ' input / ' + formatNum(s.total_output_tokens || 0) + ' output';

  document.getElementById('stat-cached-tokens').textContent = formatNum(s.cached_tokens || 0);
  const ratio = s.cache_ratio_pct !== undefined ? s.cache_ratio_pct : 0;
  document.getElementById('stat-cached-ratio').textContent = ratio + '% overall cache hit ratio';
  document.getElementById('bar-cached-ratio').style.width = ratio + '%';

  document.getElementById('stat-upstream-tokens').textContent = formatNum(s.non_cached_tokens || 0);
  const upstreamRatio = ratio > 0 ? Math.max(0, 100 - ratio).toFixed(2) : 100;
  document.getElementById('stat-upstream-ratio').textContent = upstreamRatio + '% hit the provider directly';
  document.getElementById('bar-upstream-ratio').style.width = upstreamRatio + '%';
}

function renderHealth(health) {
  const container = document.getElementById('health-details');
  const badgeEl = document.getElementById('badge-health');

  if (!health) {
    badgeEl.className = 'badge unknown';
    badgeEl.textContent = 'UNKNOWN';
    container.innerHTML = '<div style="color: var(--text-secondary)">No health status reported</div>';
    return;
  }

  badgeEl.className = 'badge ' + (health.status || 'unknown');
  badgeEl.textContent = health.status || 'UNKNOWN';

  const data = health.data || {};
  let html = '';
  Object.keys(data).forEach(key => {
    const val = data[key];
    let statusText = 'UNKNOWN';
    let statusClass = 'unknown';

    if (val === true || val === 'ok' || val === 'connected' || (val && val.status === 'ok')) {
      statusText = 'HEALTHY';
      statusClass = 'ok';
    } else if (val === false || val === 'error' || val === 'disconnected') {
      statusText = 'ERROR';
      statusClass = 'error';
    } else if (val && typeof val === 'object') {
      statusText = (val.status || 'unknown').toUpperCase();
      statusClass = val.status || 'unknown';
    } else if (val) {
      statusText = String(val).toUpperCase();
      statusClass = 'warning';
    }

    html += '<div class="item-row">' +
      '<div class="item-label">' + key.replace(/_/g, ' ') + '</div>' +
      '<div class="item-value">' + badge(statusClass) + '</div>' +
      '</div>';
  });

  container.innerHTML = html;
}

function renderCacheBreakdown(ta) {
  const body = document.getElementById('cache-types-table-body');
  if (!ta || !ta.data || !ta.data.summary || !ta.data.summary.by_cache_type) {
    body.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-secondary)">No cache type breakdown available</td></tr>';
    return;
  }

  const cache = ta.data.summary.by_cache_type;
  let html = '';

  const displayNames = {
    'gateway': 'Gateway-Engine Cache (Redis local)',
    'litellm': 'LiteLLM router Cache (upstream pool)',
    'provider': 'Provider Prompt Caching (e.g. Claude)'
  };

  Object.keys(cache).forEach(key => {
    const item = cache[key] || {};
    html += '<tr>' +
      '<td><b>' + (displayNames[key] || key) + '</b></td>' +
      '<td style="font-feature-settings: \'tnum\';">' + formatNum(item.input_tokens || 0) + '</td>' +
      '<td style="font-feature-settings: \'tnum\';">' + formatNum(item.output_tokens || 0) + '</td>' +
      '<td style="font-feature-settings: \'tnum\'; font-weight: 600;">' + formatNum(item.total_tokens || item.input_tokens || 0) + '</td>' +
      '</tr>';
  });

  body.innerHTML = html;
}

function renderModelsTable(ta) {
  const body = document.getElementById('models-table-body');
  if (!ta || !ta.data || !ta.data.by_model || ta.data.by_model.length === 0) {
    body.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-secondary)">No model usage data recorded</td></tr>';
    return;
  }

  let html = '';
  ta.data.by_model.forEach(m => {
    const total = m.total_tokens || 0;
    const cached = m.cached_tokens || 0;
    const ratio = total > 0 ? ((cached / total) * 100).toFixed(1) : '0.0';

    html += '<tr>' +
      '<td><b>' + (m.model || m.canonical_model_id || '-') + '</b></td>' +
      '<td><span class="badge unknown">' + (m.provider || '-') + '</span></td>' +
      '<td style="font-feature-settings: \'tnum\'; font-weight: 500;">' + formatNum(total) + '</td>' +
      '<td style="font-feature-settings: \'tnum\'; color: var(--text-secondary)">' + formatNum(cached) + '</td>' +
      '<td>' +
        '<div class="table-progress">' +
          '<span style="font-weight: 600; width: 45px; text-align: right;">' + ratio + '%</span>' +
          '<div class="table-progress-bar"><div class="table-progress-fill" style="width: ' + ratio + '%"></div></div>' +
        '</div>' +
      '</td>' +
      '</tr>';
  });

  body.innerHTML = html;
}

function renderProvidersTable(ta) {
  const body = document.getElementById('providers-table-body');
  if (!ta || !ta.data || !ta.data.by_provider || ta.data.by_provider.length === 0) {
    body.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-secondary)">No provider usage data recorded</td></tr>';
    return;
  }

  let html = '';
  ta.data.by_provider.forEach(p => {
    const total = p.total_tokens || 0;
    const cached = p.cached_tokens || 0;
    const ratio = total > 0 ? ((cached / total) * 100).toFixed(1) : '0.0';

    html += '<tr>' +
      '<td style="text-transform: capitalize;"><b>' + p.provider + '</b></td>' +
      '<td style="font-feature-settings: \'tnum\';">' + p.model_count + '</td>' +
      '<td style="font-feature-settings: \'tnum\'; font-weight: 500;">' + formatNum(total) + '</td>' +
      '<td>' +
        '<div class="table-progress">' +
          '<span style="font-weight: 600; width: 45px; text-align: right;">' + ratio + '%</span>' +
          '<div class="table-progress-bar"><div class="table-progress-fill" style="width: ' + ratio + '%"></div></div>' +
        '</div>' +
      '</td>' +
      '</tr>';
  });

  body.innerHTML = html;
}

function renderConfigDetails(drift, routing) {
  const container = document.getElementById('config-details');
  let html = '';

  // Config drift status
  if (drift) {
    const isDrift = drift.status !== 'ok';
    html += '<div class="item-row">' +
      '<div class="item-label">Config Drift Status</div>' +
      '<div class="item-value">' + badge(drift.status) + '</div>' +
      '</div>';
    if (drift.data && drift.data.drift_detected !== undefined) {
      html += '<div class="item-row">' +
        '<div class="item-label">Drift Detected</div>' +
        '<div class="item-value" style="font-weight: 600; color: ' + (drift.data.drift_detected ? 'var(--warning-color)' : 'var(--ok-color)') + '">' +
        (drift.data.drift_detected ? 'YES' : 'NO') + '</div>' +
        '</div>';
    }
  }

  // Routing and policy engine status
  if (routing && routing.data) {
    const policy = routing.data.policy_engine || {};
    html += '<div class="item-row">' +
      '<div class="item-label">Policy Engine Connectivity</div>' +
      '<div class="item-value">' + (policy.redis_connected ? badge('ok') : badge('error')) + '</div>' +
      '</div>';
    if (policy.version) {
      html += '<div class="item-row">' +
        '<div class="item-label">Policy Active Version</div>' +
        '<div class="item-value" style="font-family: monospace; font-size: 0.85rem">' + policy.version + '</div>' +
        '</div>';
    }
  }

  container.innerHTML = html || '<div style="color: var(--text-secondary)">No policy data found</div>';
}

load();
</script>
</body>
</html>"""


@router.get("/admin/dashboard")
async def admin_dashboard(request: Request):
    auth_error = _require_admin_read_access(request)
    if auth_error is not None:
        return auth_error
    """Read-only operator dashboard page; renders /admin/status client-side."""
    return HTMLResponse(content=_ADMIN_DASHBOARD_HTML)
