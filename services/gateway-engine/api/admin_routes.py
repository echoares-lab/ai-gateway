import asyncio
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
import yaml
from core.admin_shared import _require_admin_key, _require_admin_read_access
from core.credential_inventory import (
    CredentialInventoryListResponse,
    CredentialInventoryStore,
    CredentialInventorySyncRequest,
    CredentialInventorySyncResponse,
    CredentialProbeResponse,
    CredentialTransition,
    record_from_auth_file,
    transition_for_record,
)
from core.model_registry import (
    ModelProbeResponse,
    ModelRegistryListResponse,
    ModelRegistryMutationResponse,
    ModelRegistryPatchRequest,
    ModelRegistryReconcileRequest,
    ModelRegistryReconcileResponse,
    ModelRegistryStore,
    ModelRegistrySyncRequest,
    ModelRegistrySyncResponse,
    ModelRegistryWriteRequest,
    build_reconcile_resources,
    diff_discovered_models,
    load_models_from_litellm_config,
    merge_discovered_model,
    record_from_cliproxy_model,
)
from core.policy import policy_version as in_process_policy_version
from core.policy.schemas import CredentialEvent
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import generate_latest

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
_credential_sync_lock = asyncio.Lock()


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

# ── Read-only admin status aggregator (issue #69) ─────────────────────────────
# Emits the admin-console.v1 contract (see docs/ADMIN_CONSOLE_DATA_CONTRACT.md).
# Read-only and operator-local by design: it never mutates state, bounds every
# external/subprocess source, and redacts secrets. A failed source degrades its
# panel to warning/unknown rather than failing the whole response.

ADMIN_SCHEMA_VERSION = "admin-console.v1"
LITELLM_CONFIG_PATH = os.environ.get("LITELLM_CONFIG_PATH", "/config/litellm-config.yaml")
GEMINI_MODEL_MAP_PATH = os.environ.get("GEMINI_MODEL_MAP_PATH", "/app/gemini-model-map.json")
ADMIN_ERROR_MAXLEN = 400
GATEWAY_ENGINE_ADMIN_KEY = os.environ.get("GATEWAY_ENGINE_ADMIN_KEY", "")
CLIPROXY_URL = os.environ.get("CLIPROXY_URL", "http://cliproxy:8317").rstrip("/")
CLIPROXY_MANAGEMENT_KEY = os.environ.get("CLIPROXY_MANAGEMENT_KEY", "")
MODEL_PROBE_TIMEOUT = float(os.environ.get("MODEL_PROBE_TIMEOUT", "8.0"))
GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC = max(
    1,
    int(os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC", "300")),
)
GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC = max(
    0,
    int(os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC", "30")),
)
GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN = os.environ.get(
    "GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN", "false"
).lower() not in (
    "0",
    "false",
    "no",
)

_SECRET_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"sk-[A-Za-z0-9._\-]{12,}"),
    re.compile(
        r"(?i)(api[_-]?key|x-management-key|authorization|token|secret|password)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9._\-]{8,}"
    ),
    re.compile(r"[A-Za-z0-9._\-]{32,}"),
]


def _admin_now_iso() -> str:
    """UTC ISO-8601 timestamp. time.gmtime avoids the banned argless datetime."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _admin_redact(text: str) -> tuple[str, bool]:
    """Redact secret-looking substrings and bound length. Returns (text, redacted)."""
    if not text:
        return "", False
    redacted = False
    out = text
    for pat in _SECRET_PATTERNS:
        new = pat.sub("[redacted]", out)
        if new != out:
            redacted = True
            out = new
    if len(out) > ADMIN_ERROR_MAXLEN:
        out = out[:ADMIN_ERROR_MAXLEN] + "…"
    return out, redacted


def _admin_error(code: str, message: str, source: str) -> dict:
    msg, redacted = _admin_redact(message)
    return {"code": code, "message": msg, "source": source, "redacted": redacted}


def _admin_panel(status: str, source: str, freshness_seconds, errors: list, data: dict) -> dict:
    return {
        "status": status,
        "source": source,
        "freshness_seconds": freshness_seconds,
        "errors": errors,
        "data": data,
    }


def _admin_load_litellm_config() -> tuple[dict | None, list[dict]]:
    """Load litellm-config.yaml. Returns (config_or_None, errors)."""
    path = _main_attr("LITELLM_CONFIG_PATH", LITELLM_CONFIG_PATH)
    try:
        with open(path) as fh:
            return yaml.safe_load(fh) or {}, []
    except FileNotFoundError:
        return None, [
            _admin_error(
                "config_not_found",
                f"{path} not found",
                "repo:litellm-config.yaml",
            )
        ]
    except Exception as exc:
        return None, [
            _admin_error(
                "config_parse_error",
                f"{type(exc).__name__}: {exc}",
                "repo:litellm-config.yaml",
            )
        ]


def _read_text_file_for_reconcile(path: str, source: str) -> tuple[str | None, list[dict]]:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read(), []
    except FileNotFoundError:
        return None, [_admin_error("file_not_found", f"{path} not found", source)]
    except Exception as exc:
        return None, [_admin_error("file_read_error", f"{type(exc).__name__}: {exc}", source)]


def _model_registry_store() -> ModelRegistryStore:
    override = _main_attr("_model_registry_store", _model_registry_store)
    if override is not _model_registry_store:
        return override()
    return ModelRegistryStore()


def _credential_inventory_store() -> CredentialInventoryStore:
    override = _main_attr("_credential_inventory_store", _credential_inventory_store)
    if override is not _credential_inventory_store:
        return override()
    return CredentialInventoryStore()


def _redact_credential_record(record):
    metadata = record.metadata if isinstance(record.metadata, dict) else {}
    status_message = str(metadata.get("status_message") or "")
    return record.model_copy(
        update={
            "label": "[redacted]",
            "key_fingerprint": "[redacted]",
            "metadata": {
                "status_message": _admin_redact(status_message)[0],
                "updated_at": metadata.get("updated_at", ""),
            },
        }
    )


def _redact_credential_records(records):
    return [_redact_credential_record(record) for record in records]


def _load_model_registry_with_config_fallback() -> ModelRegistryListResponse:
    store = _model_registry_store()
    registry = store.list_models()
    if registry.registry_available and registry.models:
        return ModelRegistryListResponse(
            source=registry.source,
            registry_available=True,
            models=registry.models,
            errors=registry.errors,
        )

    fallback = load_models_from_litellm_config(_main_attr("LITELLM_CONFIG_PATH", LITELLM_CONFIG_PATH))
    return ModelRegistryListResponse(
        source="litellm-config:fallback",
        registry_available=registry.registry_available,
        models=fallback.models,
        errors=[*registry.errors, *fallback.errors],
    )


def _probe_result_status(resp: httpx.Response) -> tuple[str, list[dict]]:
    if resp.status_code in (401, 403):
        return "auth_failure", []
    if resp.status_code == 404:
        return "missing_model", []
    if resp.status_code == 429:
        return "rate_limited", []
    if resp.status_code in (408, 425, 500, 502, 503, 504):
        return "temporarily_unavailable", []
    if resp.status_code < 200 or resp.status_code >= 300:
        return "error", []
    try:
        body = resp.json()
    except Exception as exc:
        return "malformed_response", [
            _admin_error(
                "probe_malformed_response",
                f"{type(exc).__name__}: {exc}",
                "litellm:/v1/chat/completions",
            )
        ]
    choices = body.get("choices") if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices:
        return "malformed_response", [
            _admin_error(
                "probe_malformed_response",
                "response did not contain a non-empty choices list",
                "litellm:/v1/chat/completions",
            )
        ]
    return "success", []


async def _probe_model_via_litellm(model_id: str) -> tuple[str, int | None, list[dict]]:
    client = _deps().get_http_client()
    if client is None:
        return (
            "error",
            None,
            [
                _admin_error(
                    "client_unavailable",
                    "http client not initialized",
                    "litellm:/v1/chat/completions",
                )
            ],
        )
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    headers = {"authorization": f"Bearer {master_key}"} if master_key else {}
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        resp = await client.post(
            f"{_deps().litellm_url}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=MODEL_PROBE_TIMEOUT,
        )
    except httpx.TimeoutException:
        return "timeout", None, []
    except httpx.HTTPError as exc:
        return (
            "error",
            None,
            [
                _admin_error(
                    "probe_http_error",
                    f"{type(exc).__name__}: {exc}",
                    "litellm:/v1/chat/completions",
                )
            ],
        )
    except Exception as exc:
        return (
            "error",
            None,
            [
                _admin_error(
                    "probe_error",
                    f"{type(exc).__name__}: {exc}",
                    "litellm:/v1/chat/completions",
                )
            ],
        )
    status, errors = _probe_result_status(resp)
    return status, resp.status_code, errors


def _admin_parse_provider_metrics(text: str) -> list[dict]:
    """Parse the provider signal series from Prometheus exposition text.

    Returns a list of {provider, model, outcome?, kind, value} for the
    gateway_engine_provider_requests_total and gateway_engine_provider_rate_limits_total series.
    """
    signals: list[dict] = []
    if not text:
        return signals
    line_re = re.compile(
        r"^(gateway_engine_provider_requests_total|gateway_engine_provider_rate_limits_total)\{([^}]*)\}\s+([0-9.eE+]+)"
    )
    label_re = re.compile(r'(\w+)="([^"]*)"')
    for line in text.splitlines():
        m = line_re.match(line)
        if not m:
            continue
        metric, labelstr, value = m.group(1), m.group(2), m.group(3)
        labels = dict(label_re.findall(labelstr))
        entry = {
            "kind": "rate_limited" if metric.endswith("rate_limits_total") else "requests",
            "provider": labels.get("provider", "unknown"),
            "model": labels.get("model", "-"),
            "value": float(value),
        }
        if "outcome" in labels:
            entry["outcome"] = labels["outcome"]
        signals.append(entry)
    return signals


def _admin_run_readonly_command(args: list[str], timeout: float = 3.0) -> tuple[str, list[dict]]:
    """Run a bounded read-only command, returning (stdout, errors). Never raises."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        if proc.returncode != 0:
            return proc.stdout or "", [
                _admin_error(
                    "command_nonzero_exit",
                    f"{' '.join(args)} exited {proc.returncode}: {proc.stderr}",
                    "subprocess",
                )
            ]
        return proc.stdout or "", []
    except FileNotFoundError:
        return "", [_admin_error("command_not_found", f"{args[0]} not found", "subprocess")]
    except subprocess.TimeoutExpired:
        return "", [
            _admin_error(
                "command_timeout",
                f"{' '.join(args)} timed out after {timeout}s",
                "subprocess",
            )
        ]
    except Exception as exc:
        return "", [_admin_error("command_error", f"{type(exc).__name__}: {exc}", "subprocess")]


def _admin_environment() -> dict:
    stack = os.environ.get("DEV_SLOT") and "dev" or "stable"
    return {
        "stack": stack,
        "gateway_engine_base_url": os.environ.get("GATEWAY_ENGINE_BASE_URL", "http://localhost:4000"),
        "litellm_ui_url": os.environ.get("LITELLM_UI_URL", "http://localhost:4001"),
        "cliproxy_management_url": os.environ.get("CLIPROXY_MANAGEMENT_URL", "http://localhost:8317/management.html"),
        "cpa_manager_url": os.environ.get("CPA_MANAGER_URL", "http://localhost:18317/management.html"),
    }


def _admin_health_panel() -> dict:
    # Gateway Engine is serving by definition; other services are linked but not
    # actively probed in v1 (avoids unbounded calls). They are marked unknown.
    env = _admin_environment()
    services = [
        {"name": "gateway-engine", "status": "ok", "endpoint": env["gateway_engine_base_url"]},
        {"name": "litellm", "status": "unknown", "endpoint": env["litellm_ui_url"]},
        {
            "name": "cliproxy",
            "status": "unknown",
            "endpoint": env["cliproxy_management_url"],
        },
        {
            "name": "cpa-manager",
            "status": "unknown",
            "endpoint": env["cpa_manager_url"],
        },
    ]
    return _admin_panel("ok", "gateway-engine:self", 0, [], {"services": services})


def _admin_models_panel(
    config: dict | None,
    visible_ids: list[str] | None,
    errors: list[dict],
    registry: ModelRegistryListResponse | None = None,
) -> dict:
    configured = []
    if config:
        for entry in config.get("model_list", []) or []:
            name = entry.get("model_name") if isinstance(entry, dict) else None
            if name:
                configured.append(name)
    registry_models = registry.models if registry is not None else []
    if registry_models:
        configured = [model.model_id for model in registry_models]
    visible = visible_ids or []
    model_prefix = _deps().model_prefix
    visible_aliases = {v[len(model_prefix) :] if v.startswith(model_prefix) else v for v in visible}
    models = []
    drift = []
    registry_by_id = {model.model_id: model for model in registry_models}
    for alias in sorted(set(configured)):
        is_visible = alias in visible_aliases
        registry_record = registry_by_id.get(alias)
        models.append(
            {
                "id": f"{model_prefix}{alias}",
                "config_alias": alias,
                "provider_family": registry_record.family if registry_record else _deps().provider_of(alias),
                "visible": is_visible,
                "configured": alias in set(configured),
                "registry_status": registry_record.status if registry_record else None,
                "registry_source": registry_record.source if registry_record else None,
                "notes": [],
            }
        )
        if not is_visible and visible_ids is not None:
            drift.append(
                {
                    "model": alias,
                    "kind": "configured_not_visible",
                    "severity": "warning",
                }
            )
    configured_set = set(configured)
    for alias in sorted(visible_aliases - configured_set):
        models.append(
            {
                "id": f"{model_prefix}{alias}",
                "config_alias": alias,
                "provider_family": _deps().provider_of(alias),
                "visible": True,
                "configured": False,
                "notes": [],
            }
        )
        if visible_ids is not None:
            drift.append(
                {
                    "model": alias,
                    "kind": "visible_not_configured",
                    "severity": "warning",
                }
            )
    status = "ok"
    panel_errors = list(errors)
    if registry is not None:
        panel_errors.extend(registry.errors)
    if panel_errors or visible_ids is None:
        status = "warning"
    if drift:
        status = "warning"
    return _admin_panel(
        status,
        (registry.source if registry is not None else "gateway-engine:/v1/models + repo:litellm-config.yaml"),
        0,
        panel_errors,
        {
            "visible_count": len(visible),
            "configured_count": len(configured),
            "registry_available": registry.registry_available if registry is not None else False,
            "prefix": model_prefix,
            "models": models,
            "drift": drift,
        },
    )


def _admin_policy_trace_enabled() -> bool:
    return _deps().admin_policy_trace_enabled()


def _record_policy_trace(
    decision: dict | None,
    evaluate_ms: float,
    *,
    error: str | None = None,
) -> None:
    """Capture last policy-engine evaluate sample for /admin/status (issue 38-15)."""
    global _policy_version_hint
    if not _admin_policy_trace_enabled():
        return
    policy_trace = _deps().policy_trace
    policy_trace.evaluate_ms = round(evaluate_ms, 2)
    policy_trace.evaluated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    policy_trace.decision = decision
    policy_trace.error = error
    if isinstance(decision, dict) and decision.get("policy_version"):
        _policy_version_hint = str(decision["policy_version"])

    _deps().record_policy_history(decision, evaluate_ms, error=error)


def _redact_policy_decision_for_admin(decision: dict) -> dict:
    """Bounded, redacted RoutingDecision sample for operator console."""
    sample: dict = {}
    for key in ("gate", "rules_applied", "policy_version"):
        if key in decision:
            sample[key] = decision[key]
    if decision.get("quota_aware_mode"):
        sample["quota_aware_mode"] = True
        creds = decision.get("deprioritized_credentials")
        if creds:
            sample["deprioritized_credentials"] = list(creds)
    if decision.get("session_key"):
        sample["session_key"] = "[redacted]"
    return sample


def _build_admin_policy_engine_data(
    *,
    redis_connected: bool | None,
    policy_version: str | None,
) -> dict | None:
    """Policy-engine trace subsection for routing panel (issue 38-15)."""
    if not _admin_policy_trace_enabled():
        return None
    data: dict = {
        "enabled": _deps().policy_engine_enabled(),
        "trace_enabled": True,
        "policy_version": policy_version or _policy_version_hint,
        "redis_connected": redis_connected,
        "last_evaluate_ms": _deps().policy_trace.evaluate_ms,
    }
    if _deps().policy_trace.decision:
        data["last_decision"] = _redact_policy_decision_for_admin(_deps().policy_trace.decision)
    if _deps().policy_trace.error:
        data["last_error"] = _admin_redact(_deps().policy_trace.error)[0]
    return data


async def _admin_policy_engine_connectivity() -> tuple[bool | None, str | None]:
    """Best-effort Redis ping and in-process policy version for admin trace."""
    redis_connected: bool | None = None
    redis = _deps().get_redis()
    if redis is not None:
        try:
            await redis.ping()
            redis_connected = True
        except Exception:
            redis_connected = False
    policy_version = _policy_version_hint or in_process_policy_version()
    return redis_connected, policy_version


def _admin_routing_panel(
    config: dict | None,
    metrics_text: str | None,
    errors: list[dict],
    *,
    policy_engine: dict | None = None,
) -> dict:
    router_settings = {}
    fallbacks = []
    if config:
        router_settings = config.get("router_settings", {}) or {}
        raw_fallbacks = (config.get("litellm_settings", {}) or {}).get("fallbacks", []) or []
        for item in raw_fallbacks:
            if isinstance(item, dict):
                for model, targets in item.items():
                    fallbacks.append({"model": model, "targets": targets})
    raw_signals = _admin_parse_provider_metrics(metrics_text or "")
    provider_signals = []
    for sig in raw_signals:
        outcome = sig.get("outcome")
        if sig["kind"] == "rate_limited":
            outcome = "rate_limited"
        elif not outcome:
            outcome = "unknown"
        provider_signals.append(
            {
                "provider": sig["provider"],
                "model": sig["model"],
                "outcome": outcome,
                "requests": int(sig["value"]),
            }
        )
    status = "ok"
    if errors or metrics_text is None:
        status = "warning"
    data = {
        "router_settings": router_settings,
        "fallbacks": fallbacks,
        "provider_signals": provider_signals,
        "cooldown_events": [],
        "websocket_policy_bypass": _deps().codex_ws_policy_bypass(),
        "websocket_policy_evaluate_enabled": _deps().policy_engine_ws_evaluate_enabled(),
        "policy_engine_enabled": _deps().policy_engine_enabled(),
    }
    if policy_engine is not None:
        data["policy_engine"] = policy_engine
    return _admin_panel(
        status,
        "repo:litellm-config.yaml + gateway-engine:/metrics",
        15,
        errors,
        data,
    )


def _admin_providers_panel() -> dict:
    # Best-effort enrichment from the read-only health command. Parsed minimally;
    # any failure degrades the panel rather than failing the endpoint.
    script = os.environ.get("CLIPROXY_SETUP_PATH", "./cliproxy-setup.sh")
    run_command = _main_attr("_admin_run_readonly_command", _admin_run_readonly_command)
    stdout, errors = run_command([script, "health"], timeout=3.0)
    providers = []
    if stdout:
        # Lines look like: "  [claude] user@example.com  active  last_refresh=..."
        for line in stdout.splitlines():
            m = re.match(r"\s*\[(\w+)\]\s+(\S+)\s+(\w+)", line)
            if m:
                providers.append(
                    {
                        "name": m.group(1),
                        "account_label": _admin_redact(m.group(2))[0],
                        "auth_status": m.group(3),
                    }
                )
    status = "ok" if providers and not errors else ("warning" if providers else "unknown")
    return _admin_panel(status, "cliproxy-setup:health", 5, errors, {"providers": providers})


def _admin_config_drift_panel(config: dict | None, config_errors: list[dict]) -> dict:
    checks = []
    errors = list(config_errors)
    checks.append(
        {
            "name": "litellm_yaml_parse",
            "status": "ok" if config is not None else "error",
        }
    )
    # hardcoded API key scan mirrors CI: api_key: <literal> not using os.environ
    hardcoded = "unknown"
    try:
        with open(_main_attr("LITELLM_CONFIG_PATH", LITELLM_CONFIG_PATH)) as fh:
            raw = fh.read()
        bad = re.findall(r"api_key:\s+[A-Za-z0-9\-]{20,}", raw)
        bad = [b for b in bad if "os.environ" not in b]
        hardcoded = "ok" if not bad else "error"
    except Exception:
        hardcoded = "unknown"
    checks.append({"name": "hardcoded_api_keys", "status": hardcoded})
    status = "ok"
    if any(c["status"] == "error" for c in checks):
        status = "error"
    elif any(c["status"] == "unknown" for c in checks) or errors:
        status = "warning"
    return _admin_panel(
        status,
        "repo:config",
        0,
        errors,
        {
            "checks": checks,
            "runtime_overrides": [],
            "missing_env_vars": [],
        },
    )


def _admin_token_analytics_panel(metrics_text: str | None, errors: list[dict]) -> dict:
    """Build token usage analytics panel from live Prometheus metrics (#117)."""
    by_provider: dict[str, dict] = {}
    by_model: list[dict] = []
    by_canonical: dict[tuple[str, str, str], dict] = {}

    if metrics_text:
        for line in metrics_text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            # Match token counters: gateway_engine_token_input_total{provider="...",model="..."} value
            m = re.match(
                r'gateway_engine_token_(input|output)_total\{provider="([^"]+)",model="([^"]+)"\}\s+([\d.e+]+)',
                line,
            )
            if not m:
                canonical_match = re.match(
                    r"gateway_engine_token_canonical_(input|output)_total\{([^}]*)\}\s+([\d.e+]+)",
                    line,
                )
                if not canonical_match:
                    continue
                kind = canonical_match.group(1)
                labels = _parse_prometheus_labels(canonical_match.group(2))
                try:
                    val = int(float(canonical_match.group(3)))
                except ValueError:
                    continue
                canonical_model_id = labels.get("canonical_model_id") or labels.get("model") or "-"
                canonical_provider = labels.get("canonical_provider") or labels.get("provider") or "-"
                canonical_family = labels.get("canonical_family") or canonical_provider
                requested_model = labels.get("model") or "-"
                key = (canonical_model_id, canonical_provider, canonical_family)
                if key not in by_canonical:
                    by_canonical[key] = {
                        "canonical_model_id": canonical_model_id,
                        "canonical_provider": canonical_provider,
                        "canonical_family": canonical_family,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "requested_models": set(),
                    }
                by_canonical[key][f"{kind}_tokens"] += val
                by_canonical[key]["requested_models"].add(requested_model)
                continue
            kind = m.group(1)
            provider = m.group(2)
            model = m.group(3)
            try:
                val = int(float(m.group(4)))
            except ValueError:
                continue

            _add_token_metric(by_provider, by_model, provider, model, kind, val)

    canonical_summary = [
        {
            "canonical_model_id": v["canonical_model_id"],
            "canonical_provider": v["canonical_provider"],
            "canonical_family": v["canonical_family"],
            "requested_models": sorted(v["requested_models"]),
            "input_tokens": v["input_tokens"],
            "output_tokens": v["output_tokens"],
            "total_tokens": v["input_tokens"] + v["output_tokens"],
        }
        for v in by_canonical.values()
    ]
    canonical_summary.sort(
        key=lambda e: e["input_tokens"] + e["output_tokens"],
        reverse=True,
    )

    # Serialise provider summary (sets -> counts)
    provider_summary = [
        {
            "provider": v["provider"],
            "model_count": len(v["models"]),
            "input_tokens": v["input_tokens"],
            "output_tokens": v["output_tokens"],
            "total_tokens": v["input_tokens"] + v["output_tokens"],
        }
        for v in by_provider.values()
    ]
    total_input = sum(p["input_tokens"] for p in provider_summary)
    total_output = sum(p["output_tokens"] for p in provider_summary)

    status = "ok" if metrics_text and not errors else "warning"
    return _admin_panel(
        status,
        "gateway-engine:/metrics (token counters)",
        0,
        errors,
        {
            "summary": {
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_tokens": total_input + total_output,
            },
            "by_provider": provider_summary,
            "by_model": sorted(
                by_model,
                key=lambda e: e["input_tokens"] + e["output_tokens"],
                reverse=True,
            ),
            "by_canonical_model": canonical_summary,
        },
    )


def _parse_prometheus_labels(raw: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for match in re.finditer(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"', raw):
        labels[match.group(1)] = match.group(2).replace(r"\"", '"').replace(r"\\", "\\")
    return labels


def _add_token_metric(
    by_provider: dict[str, dict],
    by_model: list[dict],
    provider: str,
    model: str,
    kind: str,
    val: int,
) -> None:
    if provider not in by_provider:
        by_provider[provider] = {
            "provider": provider,
            "input_tokens": 0,
            "output_tokens": 0,
            "models": set(),
        }
    by_provider[provider][f"{kind}_tokens"] += val
    by_provider[provider]["models"].add(model)

    existing = next(
        (e for e in by_model if e["model"] == model and e["provider"] == provider),
        None,
    )
    if not existing:
        existing = {
            "model": model,
            "provider": provider,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        by_model.append(existing)
    existing[f"{kind}_tokens"] += val


async def _admin_fetch_visible_models() -> tuple[list[str] | None, list[dict]]:
    """Fetch client-visible model ids from LiteLLM, server-side. Bounded; never raises."""
    client = _deps().get_http_client()
    if client is None:
        return None, [
            _admin_error(
                "client_unavailable",
                "http client not initialized",
                "gateway-engine:/v1/models",
            )
        ]
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    headers = {"authorization": f"Bearer {master_key}"} if master_key else {}
    try:
        resp = await client.get(f"{_deps().litellm_url}/v1/models", headers=headers, timeout=2.0)
        if resp.status_code != 200:
            return None, [
                _admin_error(
                    "models_http_error",
                    f"/v1/models returned {resp.status_code}",
                    "litellm:/v1/models",
                )
            ]
        data = resp.json().get("data", [])
        ids = [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]
        # The aggregator reads LiteLLM directly (no prefix); compare on bare aliases.
        return ids, []
    except Exception as exc:
        return None, [
            _admin_error(
                "models_fetch_error",
                f"{type(exc).__name__}: {exc}",
                "litellm:/v1/models",
            )
        ]


async def _admin_fetch_metrics_text() -> tuple[str | None, list[dict]]:
    """Read the local Prometheus exposition for provider signal parsing."""
    try:
        return generate_latest().decode("utf-8", errors="replace"), []
    except Exception as exc:
        return None, [_admin_error("metrics_error", f"{type(exc).__name__}: {exc}", "gateway-engine:/metrics")]


async def _fetch_cliproxy_auth_files() -> tuple[list[dict], list[dict]]:
    client = _deps().get_http_client()
    if client is None:
        return [], [
            _admin_error(
                "client_unavailable",
                "http client not initialized",
                "cliproxy:/v0/management/auth-files",
            )
        ]
    management_key = _main_attr("CLIPROXY_MANAGEMENT_KEY", CLIPROXY_MANAGEMENT_KEY) or os.environ.get(
        "CLIPROXY_MANAGEMENT_KEY", ""
    )
    if not management_key:
        return [], [
            _admin_error(
                "management_key_missing",
                "CLIPROXY_MANAGEMENT_KEY is required",
                "cliproxy:/v0/management/auth-files",
            )
        ]
    try:
        resp = await client.get(
            f"{_main_attr('CLIPROXY_URL', CLIPROXY_URL)}/v0/management/auth-files",
            headers={"x-management-key": management_key},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return [], [
                _admin_error(
                    "cliproxy_http_error",
                    f"/v0/management/auth-files returned {resp.status_code}",
                    "cliproxy:/v0/management/auth-files",
                )
            ]
        body = resp.json()
        files = body.get("files") if isinstance(body, dict) else None
        if not isinstance(files, list):
            return [], [
                _admin_error(
                    "cliproxy_bad_response",
                    "response missing files array",
                    "cliproxy:/v0/management/auth-files",
                )
            ]
        return [item for item in files if isinstance(item, dict)], []
    except Exception as exc:
        return [], [
            _admin_error(
                "cliproxy_fetch_error",
                f"{type(exc).__name__}: {exc}",
                "cliproxy:/v0/management/auth-files",
            )
        ]


_PROVIDER_LABELS: dict[str, str] = {
    "claude": "Claude",
    "antigravity": "Antigravity",
    "codex": "Codex",
    "gemini": "Gemini",
    "gemini-cli": "Gemini CLI",
    "kimi": "Kimi",
    "openai": "OpenAI",
}

_PROVIDER_MODEL_SCOPE: dict[str, str] = {
    "claude": "All Claude models",
    "antigravity": "Gemini and Claude/GPT models",
    "codex": "All GPT/Codex models",
    "gemini": "Gemini models",
    "gemini-cli": "Gemini CLI models",
    "kimi": "Kimi models",
    "openai": "All OpenAI models",
}

# CLIProxy zero-time sentinel meaning "no data captured yet"
_GO_ZERO_TIME = "0001-01-01T00:00:00Z"


async def _fetch_cliproxy_quota_status() -> tuple[list[dict], list[dict]]:
    client = _deps().get_http_client()
    if client is None:
        return [], [
            _admin_error(
                "client_unavailable",
                "http client not initialized",
                "cliproxy:/v0/management/quota-status",
            )
        ]
    management_key = _main_attr("CLIPROXY_MANAGEMENT_KEY", CLIPROXY_MANAGEMENT_KEY) or os.environ.get(
        "CLIPROXY_MANAGEMENT_KEY", ""
    )
    if not management_key:
        return [], [
            _admin_error(
                "management_key_missing",
                "CLIPROXY_MANAGEMENT_KEY is required",
                "cliproxy:/v0/management/quota-status",
            )
        ]
    try:
        resp = await client.get(
            f"{_main_attr('CLIPROXY_URL', CLIPROXY_URL)}/v0/management/quota-status",
            headers={"x-management-key": management_key},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return [], [
                _admin_error(
                    "cliproxy_http_error",
                    f"/v0/management/quota-status returned {resp.status_code}",
                    "cliproxy:/v0/management/quota-status",
                )
            ]
        body = resp.json()
        credentials = body.get("credentials") if isinstance(body, dict) else None
        if not isinstance(credentials, list):
            return [], [
                _admin_error(
                    "cliproxy_bad_response",
                    "response missing credentials array",
                    "cliproxy:/v0/management/quota-status",
                )
            ]
        return [item for item in credentials if isinstance(item, dict)], []
    except Exception as exc:
        return [], [
            _admin_error(
                "cliproxy_fetch_error",
                f"{type(exc).__name__}: {exc}",
                "cliproxy:/v0/management/quota-status",
            )
        ]


async def _fetch_cliproxy_models_for_registry() -> tuple[list[dict], list[dict]]:
    client = _deps().get_http_client()
    if client is None:
        return [], [
            _admin_error(
                "client_unavailable",
                "http client not initialized",
                "cliproxy:/v1/models",
            )
        ]
    api_key = os.environ.get("CLIPROXY_API_KEY", "").strip()
    if not api_key:
        return [], [
            _admin_error(
                "cliproxy_api_key_missing",
                "CLIPROXY_API_KEY is required",
                "cliproxy:/v1/models",
            )
        ]
    try:
        resp = await client.get(
            f"{_main_attr('CLIPROXY_URL', CLIPROXY_URL)}/v1/models",
            headers={"authorization": f"Bearer {api_key}"},
            timeout=5.0,
        )
        if resp.status_code != 200:
            return [], [
                _admin_error(
                    "cliproxy_http_error",
                    f"/v1/models returned {resp.status_code}",
                    "cliproxy:/v1/models",
                )
            ]
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            return [], [
                _admin_error(
                    "cliproxy_bad_response",
                    "response missing data array",
                    "cliproxy:/v1/models",
                )
            ]
        return [item for item in data if isinstance(item, dict)], []
    except Exception as exc:
        return [], [
            _admin_error(
                "cliproxy_fetch_error",
                f"{type(exc).__name__}: {exc}",
                "cliproxy:/v1/models",
            )
        ]


async def _emit_credential_transition_to_policy(transition: CredentialTransition) -> bool:
    event = CredentialEvent(
        credential_id=transition.credential_id,
        provider=transition.provider,
        previous_status=transition.previous_status,
        new_status=transition.new_status,
        cool_down_until=transition.cool_down_until,
        reason=transition.reason,
    )
    return await _deps().process_credential_event(event)


async def _sync_credentials_from_cliproxy(
    body: CredentialInventorySyncRequest,
) -> CredentialInventorySyncResponse:
    """Sync CLIProxy auth-file state into credential_inventory."""
    async with _credential_sync_lock:
        store = _credential_inventory_store()
        files, errors = await _fetch_cliproxy_auth_files()
        credentials = [record_from_auth_file(item) for item in files]
        transitions: list[CredentialTransition] = []
        imported = 0

        if errors:
            return CredentialInventorySyncResponse(
                accepted=False,
                dry_run=body.dry_run,
                registry_available=store.enabled,
                discovered_count=len(credentials),
                imported_count=0,
                credentials=_redact_credential_records(credentials),
                errors=errors,
            )

        old_statuses: dict[str, str] = {}
        if store.enabled:
            try:
                old_statuses = store.existing_statuses()
            except Exception as exc:
                errors.append(
                    _admin_error(
                        "registry_read_error",
                        f"{type(exc).__name__}: {exc}",
                        "postgres:credential_inventory",
                    )
                )
        else:
            errors.append(
                _admin_error(
                    "registry_unavailable",
                    "DATABASE_URL or psycopg2 unavailable",
                    "postgres:credential_inventory",
                )
            )

        for credential in credentials:
            transition = transition_for_record(credential, old_statuses.get(credential.credential_id))
            if transition is not None:
                transitions.append(transition)

        if not body.dry_run and store.enabled and not errors:
            try:
                imported = store.upsert_credentials(credentials)
            except Exception as exc:
                errors.append(
                    _admin_error(
                        "registry_write_error",
                        f"{type(exc).__name__}: {exc}",
                        "postgres:credential_inventory",
                    )
                )
            else:
                for transition in transitions:
                    try:
                        emit_transition = _main_attr(
                            "_emit_credential_transition_to_policy",
                            _emit_credential_transition_to_policy,
                        )
                        await emit_transition(transition)
                    except Exception as exc:
                        errors.append(
                            _admin_error(
                                "policy_event_error",
                                f"{type(exc).__name__}: {exc}",
                                "gateway-engine:policy-event",
                            )
                        )
        elif body.dry_run:
            imported = len(credentials)

        return CredentialInventorySyncResponse(
            accepted=not errors,
            dry_run=body.dry_run,
            registry_available=store.enabled,
            discovered_count=len(credentials),
            imported_count=imported,
            credentials=_redact_credential_records(credentials),
            transitions=transitions,
            errors=errors,
        )


async def _run_scheduled_credential_sync() -> CredentialInventorySyncResponse:
    response = await _sync_credentials_from_cliproxy(
        CredentialInventorySyncRequest(
            dry_run=_main_attr("GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN", GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN)
        )
    )
    log.info(
        "credential sync scheduler completed accepted=%s dry_run=%s discovered=%d imported=%d transitions=%d errors=%d",
        response.accepted,
        response.dry_run,
        response.discovered_count,
        response.imported_count,
        len(response.transitions),
        len(response.errors),
    )
    return response


async def _credential_sync_scheduler_loop() -> None:
    initial_delay = _main_attr(
        "GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC",
        GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC,
    )
    interval = _main_attr(
        "GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC",
        GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC,
    )
    if initial_delay:
        await asyncio.sleep(initial_delay)
    while True:
        try:
            run_sync = _main_attr("_run_scheduled_credential_sync", _run_scheduled_credential_sync)
            await run_sync()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("credential sync scheduler failed: %s: %s", type(exc).__name__, _admin_redact(str(exc))[0])
        await asyncio.sleep(interval)


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
    """Real-time OAuth quota status aggregated from CLIProxy."""
    auth_error = _require_admin_read_access(request)
    if auth_error is not None:
        return auth_error

    (quota_creds, quota_errors), (auth_files, auth_errors) = await asyncio.gather(
        _fetch_cliproxy_quota_status(),
        _fetch_cliproxy_auth_files(),
    )

    all_errors = quota_errors + auth_errors
    if all_errors and not quota_creds:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "errors": all_errors},
        )

    # Build lookup: credential id → auth file metadata
    auth_by_id: dict[str, dict] = {f["id"]: f for f in auth_files if "id" in f}

    accounts = []
    for cred in quota_creds:
        cred_id = cred.get("id", "")
        # Skip internal CLIProxy artifacts (e.g. probe_failures.json)
        if not cred_id or cred.get("provider", "") in ("", "unknown"):
            continue
        provider = cred.get("provider", "")
        auth = auth_by_id.get(cred_id, {})

        def _nullify_zero_time(val: str | None) -> str | None:
            return None if val == _GO_ZERO_TIME else val

        utilization_pct_raw = cred.get("utilization_pct")
        resets_at = _nullify_zero_time(cred.get("resets_at"))
        captured_at = _nullify_zero_time(cred.get("captured_at"))
        resets_in = cred.get("resets_in")
        stale = bool(cred.get("stale"))
        # Treat zero utilization as null when no data has been captured yet
        utilization_pct = None if stale and utilization_pct_raw == 0 else utilization_pct_raw

        accounts.append(
            {
                "credential_id": cred_id,
                "email": auth.get("email") or cred.get("label", ""),
                "provider": provider,
                "provider_label": _PROVIDER_LABELS.get(provider, provider),
                "account_status": "disabled" if auth.get("disabled") else auth.get("status", "unknown"),
                "disabled": bool(auth.get("disabled")),
                "applies_to_models": _PROVIDER_MODEL_SCOPE.get(provider, f"All {provider} models"),
                "quota": {
                    "source": cred.get("quota_source", ""),
                    "stale": stale,
                    "captured_at": captured_at,
                    "windows": {
                        "5h": {"utilization_pct": None, "resets_at": None},
                        "7d": {"utilization_pct": None, "resets_at": None},
                        # CLIProxy currently returns only the binding constraint window.
                        # 5h/7d will be populated when CLIProxy exposes both separately.
                        "binding": {
                            "utilization_pct": utilization_pct,
                            "resets_at": resets_at,
                            "resets_in": resets_in,
                        },
                    },
                    "tokens_remaining": None if stale else cred.get("tokens_remaining"),
                    "tokens_limit": None if stale else cred.get("tokens_limit"),
                    "requests_remaining": None if stale else cred.get("requests_remaining"),
                    "requests_limit": None if stale else cred.get("requests_limit"),
                },
            }
        )

    accounts.sort(key=lambda a: (a["provider"], a["email"]))

    return JSONResponse(
        content={
            "status": "ok",
            "source": "cliproxy:/v0/management/quota-status",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "quota_windows_note": (
                "CLIProxy currently returns only the binding constraint window. "
                "5h and 7d will be populated when CLIProxy exposes both windows separately."
            ),
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
