"""Admin panel builders and shared admin helpers."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

import httpx
import yaml
from core.credential_inventory import (
    CredentialInventoryStore,
)
from core.model_registry import (
    ModelRegistryListResponse,
    ModelRegistryStore,
    load_models_from_litellm_config,
)
from core.policy import policy_version as in_process_policy_version
from prometheus_client import generate_latest

log = logging.getLogger("gateway-engine.admin_routes")

_policy_version_hint: str | None = None


def _main_attr(name: str, default):
    main_module = sys.modules.get("main")
    return getattr(main_module, name, default) if main_module is not None else default


def _deps():
    from api.admin_routes import _deps as _route_deps

    return _route_deps()


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
        "strict_enforcement_enabled": _deps().policy_engine_strict(),
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
        "policy_engine_strict": _deps().policy_engine_strict(),
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
    by_cache_type: dict[str, dict] = {
        "gateway": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "litellm": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "provider": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    }

    if metrics_text:
        for line in metrics_text.splitlines():
            if line.startswith("#") or not line.strip():
                continue

            # 1. Parse cache canonical metrics
            if line.startswith("gateway_engine_token_cache_canonical_"):
                m = re.match(
                    r"gateway_engine_token_cache_canonical_(input|output)_total\{([^}]*)\}\s+([\d.e+]+)",
                    line,
                )
                if m:
                    kind = m.group(1)
                    labels = _parse_prometheus_labels(m.group(2))
                    try:
                        val = int(float(m.group(3)))
                    except ValueError:
                        continue
                    canonical_model_id = labels.get("canonical_model_id") or labels.get("model") or "-"
                    canonical_provider = labels.get("canonical_provider") or labels.get("provider") or "-"
                    canonical_family = labels.get("canonical_family") or canonical_provider
                    cache_type = labels.get("cache_type") or "gateway"
                    requested_model = labels.get("model") or "-"
                    key = (canonical_model_id, canonical_provider, canonical_family)

                    if key not in by_canonical:
                        by_canonical[key] = {
                            "canonical_model_id": canonical_model_id,
                            "canonical_provider": canonical_provider,
                            "canonical_family": canonical_family,
                            "non_cached_input_tokens": 0,
                            "non_cached_output_tokens": 0,
                            "cached_input_tokens": 0,
                            "cached_output_tokens": 0,
                            "non_upstream_cached_input_tokens": 0,
                            "non_upstream_cached_output_tokens": 0,
                            "requested_models": set(),
                        }

                    by_canonical[key][f"cached_{kind}_tokens"] += val
                    if cache_type in ("gateway", "litellm"):
                        by_canonical[key][f"non_upstream_cached_{kind}_tokens"] += val
                    by_canonical[key]["requested_models"].add(requested_model)
                continue

            # 2. Parse raw canonical metrics
            elif line.startswith("gateway_engine_token_canonical_"):
                m = re.match(
                    r"gateway_engine_token_canonical_(input|output)_total\{([^}]*)\}\s+([\d.e+]+)",
                    line,
                )
                if m:
                    kind = m.group(1)
                    labels = _parse_prometheus_labels(m.group(2))
                    try:
                        val = int(float(m.group(3)))
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
                            "non_cached_input_tokens": 0,
                            "non_cached_output_tokens": 0,
                            "cached_input_tokens": 0,
                            "cached_output_tokens": 0,
                            "non_upstream_cached_input_tokens": 0,
                            "non_upstream_cached_output_tokens": 0,
                            "requested_models": set(),
                        }

                    by_canonical[key][f"non_cached_{kind}_tokens"] += val
                    by_canonical[key]["requested_models"].add(requested_model)
                continue

            # 3. Parse raw cache metrics (by provider/model)
            elif line.startswith("gateway_engine_token_cache_"):
                m = re.match(
                    r'gateway_engine_token_cache_(input|output)_total\{provider="([^"]+)",model="([^"]+)",cache_type="([^"]+)"\}\s+([\d.e+]+)',
                    line,
                )
                if m:
                    kind = m.group(1)
                    provider = m.group(2)
                    model = m.group(3)
                    cache_type = m.group(4)
                    try:
                        val = int(float(m.group(5)))
                    except ValueError:
                        continue

                    # Accumulate in by_provider
                    if provider not in by_provider:
                        by_provider[provider] = {
                            "provider": provider,
                            "non_cached_input_tokens": 0,
                            "non_cached_output_tokens": 0,
                            "cached_input_tokens": 0,
                            "cached_output_tokens": 0,
                            "non_upstream_cached_input_tokens": 0,
                            "non_upstream_cached_output_tokens": 0,
                            "models": set(),
                        }
                    by_provider[provider][f"cached_{kind}_tokens"] += val
                    if cache_type in ("gateway", "litellm"):
                        by_provider[provider][f"non_upstream_cached_{kind}_tokens"] += val
                    by_provider[provider]["models"].add(model)

                    # Accumulate in by_model
                    existing = next(
                        (e for e in by_model if e["model"] == model and e["provider"] == provider),
                        None,
                    )
                    if not existing:
                        existing = {
                            "model": model,
                            "provider": provider,
                            "non_cached_input_tokens": 0,
                            "non_cached_output_tokens": 0,
                            "cached_input_tokens": 0,
                            "cached_output_tokens": 0,
                            "non_upstream_cached_input_tokens": 0,
                            "non_upstream_cached_output_tokens": 0,
                        }
                        by_model.append(existing)
                    existing[f"cached_{kind}_tokens"] += val
                    if cache_type in ("gateway", "litellm"):
                        existing[f"non_upstream_cached_{kind}_tokens"] += val

                    # Accumulate in global by_cache_type
                    if cache_type in by_cache_type:
                        by_cache_type[cache_type][f"{kind}_tokens"] += val
                        by_cache_type[cache_type]["total_tokens"] += val
                continue

            # 4. Parse raw metrics (by provider/model)
            elif line.startswith("gateway_engine_token_"):
                m = re.match(
                    r'gateway_engine_token_(input|output)_total\{provider="([^"]+)",model="([^"]+)"\}\s+([\d.e+]+)',
                    line,
                )
                if m:
                    kind = m.group(1)
                    provider = m.group(2)
                    model = m.group(3)
                    try:
                        val = int(float(m.group(4)))
                    except ValueError:
                        continue

                    if provider not in by_provider:
                        by_provider[provider] = {
                            "provider": provider,
                            "non_cached_input_tokens": 0,
                            "non_cached_output_tokens": 0,
                            "cached_input_tokens": 0,
                            "cached_output_tokens": 0,
                            "non_upstream_cached_input_tokens": 0,
                            "non_upstream_cached_output_tokens": 0,
                            "models": set(),
                        }
                    by_provider[provider][f"non_cached_{kind}_tokens"] += val
                    by_provider[provider]["models"].add(model)

                    existing = next(
                        (e for e in by_model if e["model"] == model and e["provider"] == provider),
                        None,
                    )
                    if not existing:
                        existing = {
                            "model": model,
                            "provider": provider,
                            "non_cached_input_tokens": 0,
                            "non_cached_output_tokens": 0,
                            "cached_input_tokens": 0,
                            "cached_output_tokens": 0,
                            "non_upstream_cached_input_tokens": 0,
                            "non_upstream_cached_output_tokens": 0,
                        }
                        by_model.append(existing)
                    existing[f"non_cached_{kind}_tokens"] += val
                continue

    canonical_summary = [
        {
            "canonical_model_id": v["canonical_model_id"],
            "canonical_provider": v["canonical_provider"],
            "canonical_family": v["canonical_family"],
            "requested_models": sorted(v["requested_models"]),
            "input_tokens": v["non_cached_input_tokens"] + v["non_upstream_cached_input_tokens"],
            "output_tokens": v["non_cached_output_tokens"] + v["non_upstream_cached_output_tokens"],
            "total_tokens": v["non_cached_input_tokens"]
            + v["non_upstream_cached_input_tokens"]
            + v["non_cached_output_tokens"]
            + v["non_upstream_cached_output_tokens"],
            "non_cached_input_tokens": v["non_cached_input_tokens"],
            "non_cached_output_tokens": v["non_cached_output_tokens"],
            "non_cached_tokens": v["non_cached_input_tokens"] + v["non_cached_output_tokens"],
            "cached_input_tokens": v["cached_input_tokens"],
            "cached_output_tokens": v["cached_output_tokens"],
            "cached_tokens": v["cached_input_tokens"] + v["cached_output_tokens"],
        }
        for v in by_canonical.values()
    ]
    canonical_summary.sort(
        key=lambda e: e["total_tokens"],
        reverse=True,
    )

    # Serialise provider summary (sets -> counts)
    provider_summary = [
        {
            "provider": v["provider"],
            "model_count": len(v["models"]),
            "input_tokens": v["non_cached_input_tokens"] + v["non_upstream_cached_input_tokens"],
            "output_tokens": v["non_cached_output_tokens"] + v["non_upstream_cached_output_tokens"],
            "total_tokens": v["non_cached_input_tokens"]
            + v["non_upstream_cached_input_tokens"]
            + v["non_cached_output_tokens"]
            + v["non_upstream_cached_output_tokens"],
            "non_cached_input_tokens": v["non_cached_input_tokens"],
            "non_cached_output_tokens": v["non_cached_output_tokens"],
            "non_cached_tokens": v["non_cached_input_tokens"] + v["non_cached_output_tokens"],
            "cached_input_tokens": v["cached_input_tokens"],
            "cached_output_tokens": v["cached_output_tokens"],
            "cached_tokens": v["cached_input_tokens"] + v["cached_output_tokens"],
        }
        for v in by_provider.values()
    ]

    model_summary = [
        {
            "model": m["model"],
            "provider": m["provider"],
            "input_tokens": m["non_cached_input_tokens"] + m["non_upstream_cached_input_tokens"],
            "output_tokens": m["non_cached_output_tokens"] + m["non_upstream_cached_output_tokens"],
            "total_tokens": m["non_cached_input_tokens"]
            + m["non_upstream_cached_input_tokens"]
            + m["non_cached_output_tokens"]
            + m["non_upstream_cached_output_tokens"],
            "non_cached_input_tokens": m["non_cached_input_tokens"],
            "non_cached_output_tokens": m["non_cached_output_tokens"],
            "non_cached_tokens": m["non_cached_input_tokens"] + m["non_cached_output_tokens"],
            "cached_input_tokens": m["cached_input_tokens"],
            "cached_output_tokens": m["cached_output_tokens"],
            "cached_tokens": m["cached_input_tokens"] + m["cached_output_tokens"],
        }
        for m in by_model
    ]
    model_summary.sort(
        key=lambda e: e["total_tokens"],
        reverse=True,
    )

    total_input = sum(p["input_tokens"] for p in provider_summary)
    total_output = sum(p["output_tokens"] for p in provider_summary)
    total_tokens = total_input + total_output

    total_cached_input = sum(p["cached_input_tokens"] for p in provider_summary)
    total_cached_output = sum(p["cached_output_tokens"] for p in provider_summary)
    total_cached = total_cached_input + total_cached_output

    total_non_cached_input = sum(p["non_cached_input_tokens"] for p in provider_summary)
    total_non_cached_output = sum(p["non_cached_output_tokens"] for p in provider_summary)
    total_non_cached = total_non_cached_input + total_non_cached_output

    cache_ratio = round((total_cached / total_tokens * 100), 2) if total_tokens > 0 else 0.0

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
                "total_tokens": total_tokens,
                "cached_input_tokens": total_cached_input,
                "cached_output_tokens": total_cached_output,
                "cached_tokens": total_cached,
                "non_cached_input_tokens": total_non_cached_input,
                "non_cached_output_tokens": total_non_cached_output,
                "non_cached_tokens": total_non_cached,
                "cache_ratio_pct": cache_ratio,
                "by_cache_type": by_cache_type,
            },
            "by_provider": provider_summary,
            "by_model": model_summary,
            "by_canonical_model": canonical_summary,
        },
    )


def _parse_prometheus_labels(raw: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for match in re.finditer(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"', raw):
        labels[match.group(1)] = match.group(2).replace(r"\"", '"').replace(r"\\", "\\")
    return labels


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
    "kimi": "Kimi",
    "openai": "OpenAI",
}

_PROVIDER_MODEL_SCOPE: dict[str, str] = {
    "claude": "All Claude models",
    "antigravity": "Gemini and Claude/GPT models",
    "codex": "All GPT/Codex models",
    "kimi": "Kimi models",
    "openai": "All OpenAI models",
}

# CLIProxy provider tags to exclude from /admin/quota/status entirely. `gemini-cli`
# is the deployment's retired Gemini CLI OAuth tier (docs/ROADMAP.md "Gemini CLI
# retirement", issue #386); `gemini` covers legacy bare Gemini API-key auth files
# that are not part of gateway routing. Antigravity Gemini OAuth credentials use
# the distinct `antigravity` provider tag and are unaffected by this filter.
_QUOTA_STATUS_HIDDEN_PROVIDERS: frozenset[str] = frozenset({"gemini", "gemini-cli"})

# CLIProxy zero-time sentinel meaning "no data captured yet"
_GO_ZERO_TIME = "0001-01-01T00:00:00Z"
_UNIX_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _nullify_sentinel_reset(val: str | None) -> str | None:
    """Normalize Go year-1 and Unix-epoch reset timestamps to null."""
    if val is None or val == "":
        return None
    if not isinstance(val, str):
        return val
    if val == _GO_ZERO_TIME:
        return None
    try:
        parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        return val
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if parsed.year <= 1 or parsed == _UNIX_EPOCH_UTC:
        return None
    return val


def _live_status_from_full(full: dict) -> str:
    """Map CLIProxy full-entry live outcome; tolerate pre-status payloads."""
    status = full.get("status")
    if status in ("fresh", "unsupported", "missing", "error"):
        return status
    if not full:
        return "missing"
    # Prefer error over leftover windows/models/fetched_at (stale success fields).
    if full.get("error"):
        err = str(full["error"]).lower()
        if "does not support" in err:
            return "unsupported"
        if "access_token" in err or "no access token" in err:
            return "missing"
        return "error"
    if full.get("fetched_at"):
        return "fresh"
    if full.get("windows") or full.get("models"):
        return "fresh"
    return "missing"


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


async def _fetch_cliproxy_quota_status_full() -> tuple[list[dict], list[dict]]:
    """Call CLIProxy /v0/management/quota-status/full for live per-window breakdown."""
    client = _deps().get_http_client()
    if client is None:
        return [], [
            _admin_error(
                "client_unavailable",
                "http client not initialized",
                "cliproxy:/v0/management/quota-status/full",
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
                "cliproxy:/v0/management/quota-status/full",
            )
        ]
    try:
        resp = await client.get(
            f"{_main_attr('CLIPROXY_URL', CLIPROXY_URL)}/v0/management/quota-status/full",
            headers={"x-management-key": management_key},
            timeout=30.0,  # live provider calls; needs more time than passive quota-status
        )
        if resp.status_code != 200:
            return [], [
                _admin_error(
                    "cliproxy_http_error",
                    f"/v0/management/quota-status/full returned {resp.status_code}",
                    "cliproxy:/v0/management/quota-status/full",
                )
            ]
        body = resp.json()
        credentials = body.get("credentials") if isinstance(body, dict) else None
        if not isinstance(credentials, list):
            return [], [
                _admin_error(
                    "cliproxy_bad_response",
                    "response missing credentials array",
                    "cliproxy:/v0/management/quota-status/full",
                )
            ]
        return [item for item in credentials if isinstance(item, dict)], []
    except Exception as exc:
        return [], [
            _admin_error(
                "cliproxy_fetch_error",
                f"{type(exc).__name__}: {exc}",
                "cliproxy:/v0/management/quota-status/full",
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
