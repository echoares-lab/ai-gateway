"""Admin HTTP routes, deps, and re-exports for main.py."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from api.admin_credential_sync import (  # noqa: F401
    _credential_sync_lock,
    _credential_sync_scheduler_loop,
    _emit_credential_transition_to_policy,
    _run_scheduled_credential_sync,
    _sync_credentials_from_cliproxy,
)
from api.admin_panels import (  # noqa: F401
    _GO_ZERO_TIME,
    _PROVIDER_LABELS,
    _PROVIDER_MODEL_SCOPE,
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
    _load_model_registry_with_config_fallback,
    _model_registry_store,
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
        auth = auth_by_id.get(cred_id, {})
        full = full_by_id.get(cred_id, {})

        def _nullify_zero_time(val: str | None) -> str | None:
            return None if val == _GO_ZERO_TIME else val

        utilization_pct_raw = cred.get("utilization_pct")
        resets_at = _nullify_zero_time(cred.get("resets_at"))
        captured_at = _nullify_zero_time(cred.get("captured_at"))
        resets_in = cred.get("resets_in")
        stale = bool(cred.get("stale"))
        utilization_pct = None if stale and utilization_pct_raw == 0 else utilization_pct_raw

        # Build windows from full quota data when available; fall back to binding-only
        full_windows = full.get("windows") or {}

        def _window(key: str) -> dict:
            w = full_windows.get(key)
            if w and isinstance(w, dict):
                return {"utilization_pct": w.get("utilization_pct"), "resets_at": w.get("resets_at")}
            return {"utilization_pct": None, "resets_at": None}

        windows: dict = {
            "five_hour": _window("five_hour"),
            "seven_day": _window("seven_day"),
        }
        # Include non-null named sub-windows (opus, sonnet, oauth_apps, etc.)
        for key, w in full_windows.items():
            if key not in ("five_hour", "seven_day") and w is not None:
                windows[key] = {"utilization_pct": w.get("utilization_pct"), "resets_at": w.get("resets_at")}
        # Binding constraint from passive headers (always present, even before full data arrives)
        windows["binding"] = {
            "utilization_pct": utilization_pct,
            "resets_at": resets_at,
            "resets_in": resets_in,
        }

        quota_entry: dict = {
            "source": cred.get("quota_source", ""),
            "stale": stale,
            "captured_at": captured_at,
            "windows": windows,
            "tokens_remaining": None if stale else cred.get("tokens_remaining"),
            "tokens_limit": None if stale else cred.get("tokens_limit"),
            "requests_remaining": None if stale else cred.get("requests_remaining"),
            "requests_limit": None if stale else cred.get("requests_limit"),
        }
        # Per-model breakdown for Antigravity
        if full.get("models"):
            quota_entry["models"] = full["models"]
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

    return JSONResponse(
        content={
            "status": "ok",
            "source": "cliproxy:/v0/management/quota-status + /quota-status/full",
            "captured_at": datetime.now(timezone.utc).isoformat(),
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
    """Render registry-driven LiteLLM/Gemini config changes without writing files."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error

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
    resources = build_reconcile_resources(
        loaded.models,
        current_litellm_config=litellm_text,
        current_gemini_map=gemini_text,
        include_disabled=body.include_disabled,
    )
    return ModelRegistryReconcileResponse(
        dry_run=True,
        source=loaded.source,
        registry_available=loaded.registry_available,
        resources=resources,
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
    if not body.dry_run and not errors:
        try:
            imported = store.upsert_models(loaded_models)
        except Exception as exc:
            errors.append(
                _admin_error(
                    "registry_write_error",
                    f"{type(exc).__name__}: {exc}",
                    "postgres:model_registry",
                )
            )
    else:
        imported = len(loaded_models) if body.dry_run else 0
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

    panels = {
        "health": _admin_health_panel(),
        "models": _admin_models_panel(config, visible_ids, model_errors, registry),
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
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 1.5rem; background: #0f1115; color: #e6e6e6; }
  h1 { font-size: 1.25rem; margin: 0 0 .25rem; }
  .meta { color: #9aa0a6; font-size: .85rem; margin-bottom: 1rem; }
  .links a { color: #8ab4f8; margin-right: 1rem; font-size: .85rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 1rem; margin-top: 1rem; }
  .panel { background: #1b1e24; border: 1px solid #2a2e36; border-radius: 8px; padding: 1rem; }
  .panel h2 { font-size: 1rem; margin: 0 0 .5rem; text-transform: capitalize; }
  .badge { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .75rem; font-weight: 600; }
  .ok { background: #1e3a2b; color: #7ee2a8; }
  .warning { background: #3a341e; color: #e7d27e; }
  .error { background: #3a1e1e; color: #e78a8a; }
  .unknown { background: #2a2e36; color: #b0b6bf; }
  pre { white-space: pre-wrap; word-break: break-word; font-size: .8rem; color: #c8cdd4; margin: .5rem 0 0; max-height: 16rem; overflow: auto; }
  .err { color: #e78a8a; font-size: .8rem; }
  button { background: #2a2e36; color: #e6e6e6; border: 1px solid #3a3f49; border-radius: 6px; padding: .3rem .7rem; cursor: pointer; }
</style>
</head>
<body>
  <h1>AI Gateway — Admin Console <span id="schema" class="meta"></span></h1>
  <div class="meta">Read-only. Generated: <span id="generated">…</span>
    <button onclick="load()">Refresh</button></div>
  <div class="links" id="links"></div>
  <div id="grid" class="grid"><div class="meta">Loading…</div></div>
<script>
function badge(s){ const c=['ok','warning','error','unknown'].includes(s)?s:'unknown';
  return '<span class="badge '+c+'">'+(s||'unknown')+'</span>'; }
function esc(v){ return JSON.stringify(v,null,2)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
async function load(){
  const grid=document.getElementById('grid');
  try {
    const r=await fetch('/admin/status',{headers:{'accept':'application/json'}});
    const d=await r.json();
    document.getElementById('schema').textContent=d.schema_version||'';
    document.getElementById('generated').textContent=d.generated_at||'';
    const env=d.environment||{};
    document.getElementById('links').innerHTML=[
      ['LiteLLM UI',env.litellm_ui_url],
      ['CLIProxy',env.cliproxy_management_url],
      ['CPA-Manager',env.cpa_manager_url],
    ].filter(x=>x[1]).map(x=>'<a href="'+x[1]+'" target="_blank" rel="noopener">'+x[0]+'</a>').join('');
    const panels=d.panels||{};
    grid.innerHTML=Object.keys(panels).map(function(name){
      const p=panels[name]||{};
      const errs=(p.errors||[]).map(e=>'<div class="err">'+(e.code||'')+': '+(e.message||'')+'</div>').join('');
      return '<div class="panel"><h2>'+name+' '+badge(p.status)+'</h2>'+errs+
        '<pre>'+esc(p.data||{})+'</pre></div>';
    }).join('');
  } catch(e){ grid.innerHTML='<div class="err">Failed to load /admin/status: '+e+'</div>'; }
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
