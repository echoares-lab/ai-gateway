"""Tenancy, policy, budget, metrics, and upstream POST helpers."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import time

import httpx
from api.policy_hooks import PolicyDeniedError, PolicyHookBoundary, redact_policy_decision
from api.proxy_common import (
    _deps,
    _enable_virtual_providers,
    _http_client,
    _main_override,
    log,
)
from core.metrics import (
    PROVIDER_LATENCY,
    PROVIDER_RATE_LIMITS,
    PROVIDER_REQUESTS,
    TOKEN_CACHE_CANONICAL_INPUT,
    TOKEN_CACHE_CANONICAL_OUTPUT,
    TOKEN_CACHE_INPUT,
    TOKEN_CACHE_OUTPUT,
    TOKEN_CANONICAL_INPUT,
    TOKEN_CANONICAL_OUTPUT,
    TOKEN_CANONICAL_REQUESTS,
    TOKEN_INPUT,
    TOKEN_OUTPUT,
    TOKEN_REQUESTS,
)
from core.model_reconciliation import ReconciliationTrigger
from core.model_registry import ModelRegistryRecord, normalize_discovered_model
from core.policy.mcp_filter import McpVisibilityDenied, apply_mcp_visibility, has_denied_invocation, metadata_decision
from orchestrator import litellm_admin_get
from providers.virtual import virtual_provider

_PROVIDER_PREFIXES = (
    ("claude", "anthropic"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("gemini", "google"),
    ("grok", "xai"),
    ("kimi", "moonshot"),
    ("moonshot", "moonshot"),
    ("virt-", "virtual"),
)

_UNKNOWN_MODEL_ERROR_MAX_BYTES = 8192
_UNKNOWN_MODEL_MARKERS = ("invalid model name", "model not found", "unknown model")


def is_unknown_model_response(response: httpx.Response) -> bool:
    """Recognize bounded, typed upstream unknown-model errors."""
    if response.status_code not in (400, 404):
        return False
    content = response.content
    if len(content) > _UNKNOWN_MODEL_ERROR_MAX_BYTES:
        return False
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return False
    values = [error.get(name) for name in ("message", "type", "code")]
    provider_fields = error.get("provider_specific_fields")
    if isinstance(provider_fields, dict):
        values.extend(provider_fields.get(name) for name in ("error", "message", "type", "code"))
    return any(
        marker in value.lower() for value in values if isinstance(value, str) for marker in _UNKNOWN_MODEL_MARKERS
    )


def _log_refresh_task_result(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        log.warning("model reconciliation demand request failed: %s", type(exc).__name__)


async def _validate_and_enqueue_refresh(validate_auth, request_refresh, client_auth, normalized_model) -> None:
    try:
        validation = validate_auth(client_auth)
        if inspect.isawaitable(validation):
            validation = await validation
        validated = validation[0] if isinstance(validation, tuple) else validation
        if not validated:
            return
        result = request_refresh(ReconciliationTrigger.DEMAND, normalized_model)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        log.warning("model reconciliation demand enqueue failed: %s", type(exc).__name__)


def maybe_enqueue_unknown_model_refresh(
    response: httpx.Response,
    requested_model: str,
    *,
    client_auth: str | None,
    validate_auth=None,
    request_refresh=None,
) -> httpx.Response:
    """Enqueue trusted discovery after an authenticated unknown-model response."""
    if not client_auth or not client_auth.strip() or not is_unknown_model_response(response):
        return response
    try:
        normalized_model, _upstream_model = normalize_discovered_model(requested_model)
    except (TypeError, ValueError):
        return response
    deps = None if request_refresh is not None and validate_auth is not None else _deps()
    callback = request_refresh or deps.request_model_reconciliation
    validator = validate_auth or deps.validate_client_auth
    if callback is None or validator is None:
        return response
    try:
        task = asyncio.create_task(_validate_and_enqueue_refresh(validator, callback, client_auth, normalized_model))
        task.add_done_callback(_log_refresh_task_result)
    except Exception as exc:
        log.warning("model reconciliation demand enqueue failed: %s", type(exc).__name__)
    return response


def _provider_of(model: str) -> str:
    """Derive the provider family from a model name. Returns 'unknown' if unmatched."""
    if not model:
        return "unknown"
    m = model.lower()
    if m.startswith(_deps().model_prefix.lower()):
        m = m[len(_deps().model_prefix) :]
    for prefix, provider in _PROVIDER_PREFIXES:
        if m.startswith(prefix):
            return provider
    return "unknown"


def _model_from_content(content: bytes) -> str:
    """Best-effort extract the model name from a JSON request body for signal labels."""
    try:
        return json.loads(content).get("model", "-") or "-"
    except Exception:
        return "-"


def _outcome_for_status(status: int) -> str:
    """Classify an upstream status code into a routing outcome label."""
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    if status >= 400:
        return "client_error"
    return "success"


def _tenancy_from_token(token: str | None) -> dict:
    """Build TenancyContext fields from an ak- API key label."""
    if not token or not isinstance(token, str):
        return {}
    token = token.removeprefix("Bearer ").strip()
    if not token.startswith("ak-"):
        return {}
    parts = token.split("-")
    if len(parts) < 6:
        return {}
    return {
        "tenant_id": parts[1],
        "workspace_id": parts[2],
        "team_id": parts[3],
        "repo_name": parts[4],
        "environment": "-".join(parts[5:]),
        "api_key_label": token,
    }


def _extract_and_apply_tenancy(token: str | None, body: dict) -> dict:
    """Extract tenant, workspace, team, repo, and environment from ak- API key and inject into metadata."""
    tenant_info = _tenancy_from_token(token)
    if tenant_info:
        if "metadata" not in body or not isinstance(body["metadata"], dict):
            body["metadata"] = {}
        body["metadata"].update({k: v for k, v in tenant_info.items() if k != "api_key_label"})
    return body


def _normalize_upstream_authorization(headers: dict) -> None:
    """Swap ak- tenant labels for the LiteLLM virtual key; ak- keys are not valid upstream."""
    auth_key = None
    auth_val = None
    for key, value in headers.items():
        if key.lower() == "authorization":
            auth_key = key
            auth_val = value
            break
    token = (auth_val or "").removeprefix("Bearer ").strip()
    routing_key = os.environ.get("LITELLM_ROUTING_KEY") or os.environ.get("LITELLM_MASTER_KEY", "")
    if routing_key and (not token or token.startswith("ak-")):
        headers[auth_key or "authorization"] = f"Bearer {routing_key}"


def _auth_fingerprint(authorization: str | None) -> str | None:
    """Stable tenant discriminator for cache keys (sha256 of bearer token / auth value)."""
    if not authorization or not isinstance(authorization, str):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    return hashlib.sha256(token.encode()).hexdigest()


_quota_headroom_cache: list[dict] | None = None
_team_alias_index: dict[str, str] | None = None
_team_alias_index_at: float = 0.0
_budget_snapshot_cache: dict[str, tuple[float, dict]] = {}


def _prom_counter_value(counter, **labels) -> float:
    for metric in counter.collect():
        for sample in metric.samples:
            if all(sample.labels.get(k) == v for k, v in labels.items()):
                return sample.value
    return 0.0


def _label_model(model: str) -> str:
    if not model:
        return "-"
    if model.startswith(_deps().model_prefix):
        return model[len(_deps().model_prefix) :]
    return model


def _build_rate_limit_hints(model: str) -> list[dict]:
    provider = _provider_of(model)
    label_model = _label_model(model)
    rl_count = int(_prom_counter_value(PROVIDER_RATE_LIMITS, provider=provider, model=label_model))
    if rl_count <= 0:
        return []
    return [
        {
            "provider": provider,
            "rolling_429_count_5m": rl_count,
            "pre_emptive_degraded": True,
        }
    ]


def _load_quota_headroom_hints() -> list[dict]:
    if _quota_headroom_cache is not None:
        return list(_quota_headroom_cache)
    raw = os.environ.get("QUOTA_HEADROOM_JSON", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Invalid QUOTA_HEADROOM_JSON — ignoring quota headroom hints")
        return []
    return data if isinstance(data, list) else []


def _team_slug_from_tenancy(tenancy: dict) -> str | None:
    parts = [
        tenancy.get("tenant_id"),
        tenancy.get("workspace_id"),
        tenancy.get("team_id"),
    ]
    if not all(parts):
        return None
    return "-".join(parts)


def _budget_pct_used(spend: float | None, max_budget: float | None) -> float | None:
    if max_budget is None or max_budget <= 0:
        return None
    return min(100.0, (spend or 0.0) / max_budget * 100.0)


def _parse_team_info_to_budget(team_info: dict) -> dict:
    max_budget = team_info.get("max_budget")
    spend = team_info.get("spend") or 0.0
    snapshot: dict = {
        "team_budget_usd": max_budget,
        "team_spend_usd": spend if max_budget is not None else None,
        "team_budget_pct_used": _budget_pct_used(spend, max_budget),
    }
    for src, dst in (
        ("rpm_limit_remaining", "rpm_remaining"),
        ("tpm_limit_remaining", "tpm_remaining"),
    ):
        if team_info.get(src) is not None:
            snapshot[dst] = team_info[src]
    return snapshot


def _load_budget_snapshot_override() -> dict | None:
    raw = os.environ.get("TEAM_BUDGET_SNAPSHOT_JSON", "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Invalid TEAM_BUDGET_SNAPSHOT_JSON — ignoring budget snapshot override")
        return None
    return data if isinstance(data, dict) else None


async def _resolve_litellm_team_id(team_alias: str) -> str | None:
    global _team_alias_index, _team_alias_index_at
    now = time.monotonic()
    if _team_alias_index is None or (now - _team_alias_index_at) > _deps().team_budget_cache_ttl_sec:
        data = await litellm_admin_get("/team/list")
        teams = []
        if isinstance(data, list):
            teams = data
        elif isinstance(data, dict):
            teams = data.get("teams") or []
        _team_alias_index = {
            t["team_alias"]: t["team_id"]
            for t in teams
            if isinstance(t, dict) and t.get("team_alias") and t.get("team_id")
        }
        _team_alias_index_at = now
    return (_team_alias_index or {}).get(team_alias)


async def _fetch_litellm_team_budget(team_alias: str) -> dict | None:
    cached = _budget_snapshot_cache.get(team_alias)
    now = time.monotonic()
    if cached and cached[0] > now:
        return dict(cached[1])

    team_id = await _resolve_litellm_team_id(team_alias)
    if not team_id:
        return None
    data = await litellm_admin_get("/team/info", params={"team_id": team_id})
    if not data:
        return None
    team_info = data.get("team_info") if isinstance(data.get("team_info"), dict) else data
    if not isinstance(team_info, dict):
        return None
    snapshot = _parse_team_info_to_budget(team_info)
    _budget_snapshot_cache[team_alias] = (now + _deps().team_budget_cache_ttl_sec, snapshot)
    return snapshot


async def _load_team_budget_snapshot(tenancy: dict) -> dict | None:
    if not _deps().team_budget_snapshot_enabled():
        return None
    override = _load_budget_snapshot_override()
    if override is not None:
        return override
    if not tenancy:
        return None
    aliases = []
    slug = _team_slug_from_tenancy(tenancy)
    if slug:
        aliases.append(slug)
    repo_name = tenancy.get("repo_name")
    if repo_name and repo_name not in aliases:
        aliases.append(repo_name)
    for alias in aliases:
        snapshot = await _fetch_litellm_team_budget(alias)
        if snapshot is not None:
            return snapshot
    return None


def _request_capabilities(body: dict) -> dict:
    model = body.get("model", "")
    tools = body.get("tools") or []
    messages = body.get("messages") or []
    has_vision = False
    active_tool_chain = bool(tools)
    for msg in messages:
        if msg.get("role") == "tool":
            active_tool_chain = True
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type", "") in ("image_url", "input_image") or "image_url" in item:
                has_vision = True
    return {
        "has_tools": bool(tools),
        "has_vision": has_vision,
        "active_tool_chain": active_tool_chain,
        "model_family": _provider_of(model) if model else None,
    }


def _compact_string_list(value, *, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item)
        if text and text not in out:
            out.append(text[:128])
        if len(out) >= limit:
            break
    return out


def _policy_registry_metadata_from_record(record: ModelRegistryRecord) -> dict:
    policy_metadata = record.policy_metadata if isinstance(record.policy_metadata, dict) else {}
    capabilities = {
        key: value
        for key, value in {
            "tools": record.supports_tools,
            "vision": record.supports_vision,
        }.items()
        if value is not None
    }
    payload = {
        "canonical_model_id": record.model_id,
        "provider": record.provider,
        "family": record.family,
        "upstream_model": record.upstream_model,
        "litellm_model": record.litellm_model,
        "enabled": record.enabled,
        "status": record.status,
        "cost_tier": record.cost_tier,
        "capabilities": capabilities,
        "probe_status": record.probe_status,
        "probe_http_status": record.probe_http_status,
    }
    fallbacks = _compact_string_list(policy_metadata.get("fallbacks"))
    aliases = _compact_string_list(policy_metadata.get("aliases"))
    backing_credentials = _compact_string_list(
        policy_metadata.get("deployment_credentials") or policy_metadata.get("backing_credentials"),
        limit=16,
    )
    if fallbacks:
        payload["fallbacks"] = fallbacks
    if aliases:
        payload["aliases"] = aliases
    if backing_credentials:
        payload["deployment_credentials"] = backing_credentials
    return {key: value for key, value in payload.items() if value is not None}


def _deployment_credentials_for_policy(model: str, registry_metadata: dict) -> dict[str, list[str]]:
    credentials = registry_metadata.get("deployment_credentials")
    if not isinstance(credentials, list):
        return {}
    cred_ids = [cred for cred in credentials if isinstance(cred, str) and cred]
    if not cred_ids:
        return {}

    requested = model[len("AI-Gateway:") :] if model.startswith("AI-Gateway:") else model
    canonical = registry_metadata.get("canonical_model_id")
    deployments = {}
    for deployment in (canonical, requested, requested.replace(".", "-") if requested else None):
        if isinstance(deployment, str) and deployment:
            deployments[deployment] = cred_ids
    return deployments


def _model_registry_metadata_for_policy(model: str) -> dict | None:
    override = _main_override("_model_registry_metadata_for_policy", _model_registry_metadata_for_policy)
    if override is not None:
        return override(model)
    requested = model[len("AI-Gateway:") :] if model.startswith("AI-Gateway:") else model
    if not requested:
        return None
    candidates = {requested, requested.replace(".", "-")}
    if requested.startswith("openai/"):
        stripped = requested[len("openai/") :]
        candidates.update({stripped, stripped.replace(".", "-")})
    try:
        loaded = _deps().load_model_registry()
    except Exception as exc:
        log.warning("model registry metadata lookup failed (%s) — fail-open", exc)
        return None
    for record in loaded.models:
        if record.model_id in candidates or record.upstream_model in candidates or record.litellm_model in candidates:
            return _policy_registry_metadata_from_record(record)
    return None


def _build_routing_context(token: str | None, body: dict, *, budget: dict | None = None) -> dict:
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    model = body.get("model", "")
    context_metadata = {}
    registry_metadata = _model_registry_metadata_for_policy(model)
    if registry_metadata:
        context_metadata["model_registry"] = registry_metadata
        deployment_credentials = _deployment_credentials_for_policy(model, registry_metadata)
        if deployment_credentials:
            context_metadata["deployment_credentials"] = deployment_credentials
            context_metadata["backing_credentials"] = deployment_credentials
    ctx = {
        "requested_model": model,
        "tenancy": _tenancy_from_token(token),
        "capabilities": _request_capabilities(body),
        "agent_id": metadata.get("agent_id"),
        "session_id": metadata.get("session_id") or metadata.get("litellm_session_id"),
        "rate_limits": _build_rate_limit_hints(model),
        "quota_headroom": _load_quota_headroom_hints(),
        "metadata": context_metadata,
    }
    if budget is not None:
        ctx["budget"] = budget
    return ctx


async def _evaluate_policy_engine(context: dict) -> dict | None:
    """In-process policy evaluate; records admin trace; fail-open on error."""
    start = time.monotonic()
    evaluator = _deps().get_policy_evaluator()
    if evaluator is None:
        log.warning("policy evaluate skipped — in-process evaluator not ready")
        _deps().record_policy_trace(None, (time.monotonic() - start) * 1000, error="evaluator unavailable")
        return None
    try:
        decision = await asyncio.wait_for(evaluator.evaluate(context), timeout=_policy_engine_timeout_seconds())
        elapsed_ms = (time.monotonic() - start) * 1000
        if decision is None:
            _deps().record_policy_trace(None, elapsed_ms, error="evaluate failed")
            return None
        if not _valid_policy_decision(decision):
            _deps().record_policy_trace(None, elapsed_ms, error="malformed decision")
            return None
        _deps().record_policy_trace(decision, elapsed_ms)
        return decision
    except asyncio.TimeoutError:
        elapsed_ms = (time.monotonic() - start) * 1000
        log.warning("policy evaluate timed out — fail-open")
        _deps().record_policy_trace(None, elapsed_ms, error="timeout")
        return None
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        log.warning("policy evaluate failed (%s) — fail-open", type(exc).__name__)
        # Keep the existing bounded diagnostic for operator compatibility while
        # avoiding raw exception reprs that may contain credentials or prompts.
        detail = str(exc).replace("\n", " ").strip()[:120] or "error"
        _deps().record_policy_trace(None, elapsed_ms, error=detail)
        return None


def _policy_engine_timeout_seconds() -> float:
    override = _main_override("POLICY_ENGINE_TIMEOUT_MS", None)
    if override is not None:
        try:
            return max(0.001, float(override) / 1000)
        except (TypeError, ValueError):
            pass
    for key in ("POLICY_ENGINE_TIMEOUT_MS", "GATEWAY_ENGINE_POLICY_ENGINE_TIMEOUT_MS"):
        raw = os.environ.get(key)
        if raw:
            try:
                return max(0.001, float(raw) / 1000)
            except ValueError:
                continue
    return 0.1


def _policy_engine_strict_enabled() -> bool:
    # Environment aliases are checked first so an operator can disable strict
    # mode immediately without replacing the running dependency graph.
    for key in ("POLICY_ENGINE_STRICT", "GATEWAY_ENGINE_POLICY_ENGINE_STRICT", "POLICY_ENGINE_ENFORCE"):
        raw = os.environ.get(key)
        if raw is not None and raw != "":
            return raw.lower() in ("1", "true", "yes")
    try:
        deps = _deps()
    except RuntimeError:
        deps = None
    strict_getter = getattr(deps, "policy_engine_strict", None)
    if strict_getter is not None:
        return bool(strict_getter())
    override = _main_override("POLICY_ENGINE_STRICT", None)
    if override is not None:
        return bool(override)
    return False


def _mcp_visibility_enabled() -> bool:
    override = _main_override("MCP_VISIBILITY_ENABLED", None)
    if override is not None:
        return bool(override)
    return os.environ.get("MCP_VISIBILITY_ENABLED", "").lower() in ("1", "true", "yes")


def _valid_policy_decision(decision: object) -> bool:
    return isinstance(decision, dict) and decision.get("gate") in {"allow", "deny"}


async def _apply_policy_engine(token: str | None, body: dict) -> dict:
    if not _deps().policy_engine_enabled():
        return body
    try:
        tenancy = _tenancy_from_token(token)
        budget = await _load_team_budget_snapshot(tenancy)
        decision = await _evaluate_policy_engine(_build_routing_context(token, body, budget=budget))
        if decision is None:
            return body
        if decision.get("gate") == "deny" and _policy_engine_strict_enabled():
            raise PolicyDeniedError(decision)
        if _mcp_visibility_enabled() and decision.get("gate") == "allow":
            if has_denied_invocation(body, decision):
                raise McpVisibilityDenied
            body = apply_mcp_visibility(body, decision)
        if "metadata" not in body or not isinstance(body["metadata"], dict):
            body["metadata"] = {}
        body["metadata"]["routing_decision"] = metadata_decision(decision, enabled=_mcp_visibility_enabled())
        return body
    except PolicyDeniedError:
        raise
    except McpVisibilityDenied as exc:
        raise PolicyDeniedError({"gate": "deny", "rules_applied": ["mcp:visibility_denied"]}) from exc
    except Exception as exc:
        log.warning("policy apply failed (%s) — fail-open", exc)
        return body


def create_policy_hooks() -> PolicyHookBoundary:
    """Create the explicit policy boundary from configured request-path hooks."""
    return PolicyHookBoundary(
        enabled=lambda: _deps().policy_engine_enabled(),
        build_context=_build_routing_context,
        evaluate=_evaluate_policy_engine,
        apply=_apply_policy_engine,
        record_trace=lambda *args, **kwargs: _deps().record_policy_trace(*args, **kwargs),
        redact_decision=redact_policy_decision,
    )


def _record_token_usage(model: str, response_json: dict, headers: dict | httpx.Headers | None = None) -> None:
    """Extract and record token usage from API response for analytics (#117)."""
    provider = _provider_of(model)
    label_model = model or "-"
    try:
        usage = response_json.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if input_tokens > 0 or output_tokens > 0:
            is_litellm_cache = False
            if headers:
                # Check both lowercase and exact casing for x-litellm-cache
                cache_header = headers.get("x-litellm-cache") or headers.get("X-LiteLLM-Cache")
                if cache_header == "HIT":
                    is_litellm_cache = True

            registry_metadata = _model_registry_metadata_for_policy(model)
            canonical_model_id = label_model
            canonical_provider = provider
            canonical_family = provider
            if registry_metadata:
                canonical_model_id = registry_metadata.get("canonical_model_id") or label_model
                canonical_provider = registry_metadata.get("provider") or provider
                canonical_family = registry_metadata.get("family") or canonical_provider

            if is_litellm_cache:
                # Record under litellm cache type
                TOKEN_CACHE_INPUT.labels(provider, label_model, "litellm").inc(input_tokens)
                TOKEN_CACHE_OUTPUT.labels(provider, label_model, "litellm").inc(output_tokens)
                if registry_metadata:
                    TOKEN_CACHE_CANONICAL_INPUT.labels(
                        provider,
                        label_model,
                        canonical_model_id,
                        canonical_provider,
                        canonical_family,
                        "litellm",
                    ).inc(input_tokens)
                    TOKEN_CACHE_CANONICAL_OUTPUT.labels(
                        provider,
                        label_model,
                        canonical_model_id,
                        canonical_provider,
                        canonical_family,
                        "litellm",
                    ).inc(output_tokens)
            else:
                # Record normal upstream non-cached consumption
                TOKEN_INPUT.labels(provider, label_model).inc(input_tokens)
                TOKEN_OUTPUT.labels(provider, label_model).inc(output_tokens)
                TOKEN_REQUESTS.labels(provider, label_model).inc()
                if registry_metadata:
                    TOKEN_CANONICAL_INPUT.labels(
                        provider,
                        label_model,
                        canonical_model_id,
                        canonical_provider,
                        canonical_family,
                    ).inc(input_tokens)
                    TOKEN_CANONICAL_OUTPUT.labels(
                        provider,
                        label_model,
                        canonical_model_id,
                        canonical_provider,
                        canonical_family,
                    ).inc(output_tokens)
                    TOKEN_CANONICAL_REQUESTS.labels(
                        provider,
                        label_model,
                        canonical_model_id,
                        canonical_provider,
                        canonical_family,
                    ).inc()

            # Record provider prompt cache hits if details are populated
            prompt_details = usage.get("prompt_tokens_details") or {}
            cached_prompt = prompt_details.get("cached_tokens", 0)
            if cached_prompt > 0:
                TOKEN_CACHE_INPUT.labels(provider, label_model, "provider").inc(cached_prompt)
                if registry_metadata:
                    TOKEN_CACHE_CANONICAL_INPUT.labels(
                        provider,
                        label_model,
                        canonical_model_id,
                        canonical_provider,
                        canonical_family,
                        "provider",
                    ).inc(cached_prompt)
    except (AttributeError, TypeError, KeyError):
        # Safely ignore malformed responses
        pass


def _record_cached_token_usage(model: str, response_json: dict, cache_type: str) -> None:
    """Record token metrics when served from local cache (gateway) (#117)."""
    provider = _provider_of(model)
    label_model = model or "-"
    try:
        usage = response_json.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if input_tokens > 0 or output_tokens > 0:
            TOKEN_CACHE_INPUT.labels(provider, label_model, cache_type).inc(input_tokens)
            TOKEN_CACHE_OUTPUT.labels(provider, label_model, cache_type).inc(output_tokens)
            registry_metadata = _model_registry_metadata_for_policy(model)
            if registry_metadata:
                canonical_model_id = registry_metadata.get("canonical_model_id") or label_model
                canonical_provider = registry_metadata.get("provider") or provider
                canonical_family = registry_metadata.get("family") or canonical_provider
                TOKEN_CACHE_CANONICAL_INPUT.labels(
                    provider,
                    label_model,
                    canonical_model_id,
                    canonical_provider,
                    canonical_family,
                    cache_type,
                ).inc(input_tokens)
                TOKEN_CACHE_CANONICAL_OUTPUT.labels(
                    provider,
                    label_model,
                    canonical_model_id,
                    canonical_provider,
                    canonical_family,
                    cache_type,
                ).inc(output_tokens)
    except Exception as exc:
        log.warning("failed to record cached token usage: %s", exc)


def _record_provider_signal(model: str, status: int, elapsed: float) -> None:
    """Emit passive per-provider/model routing signals for one upstream call."""
    provider = _provider_of(model)
    label_model = model or "-"
    PROVIDER_LATENCY.labels(provider, label_model).observe(elapsed)
    outcome = _outcome_for_status(status)
    PROVIDER_REQUESTS.labels(provider, label_model, outcome).inc()
    if status == 429:
        PROVIDER_RATE_LIMITS.labels(provider, label_model).inc()


async def _post_with_retry(url: str, headers: dict, content: bytes, retries: int = 2) -> httpx.Response:
    """POST to LiteLLM with retry on transient 502/503.

    Records passive per-provider/model routing signals (latency, outcome,
    rate-limit) for every attempt — see 01 Projects/AI-Gateway/Specs/ADAPTIVE_ROUTING.md (issue #59).
    """
    override = _main_override("_post_with_retry", _post_with_retry)
    if override is not None:
        return await override(url, headers, content, retries=retries)
    model = _model_from_content(content)

    if _enable_virtual_providers() and model.startswith("virt-"):
        start = time.monotonic()
        try:
            body = json.loads(content)
        except Exception:
            body = {}

        parts = model.split("-")
        status_code = 200
        if len(parts) >= 3 and parts[1] == "error":
            try:
                status_code = int(parts[2])
            except ValueError:
                pass

        if status_code == 200:
            v_resp = virtual_provider.oai_to_resp(body, model)
        else:
            v_resp = virtual_provider.simulate_error(status_code)

        elapsed = time.monotonic() - start
        _record_provider_signal(model, status_code, elapsed)

        return httpx.Response(
            status_code=status_code,
            content=json.dumps(v_resp).encode("utf-8"),
            request=httpx.Request("POST", url, headers=headers, content=content),
        )

    for attempt in range(retries + 1):
        start = time.monotonic()
        resp = await _http_client().post(url, headers=headers, content=content)
        _record_provider_signal(model, resp.status_code, time.monotonic() - start)
        if resp.status_code in (502, 503) and attempt < retries:
            log.warning("LiteLLM %d on attempt %d, retrying…", resp.status_code, attempt + 1)
            await asyncio.sleep(1)
            continue
        return resp
    return resp


def _maybe_force_model(request, body: dict) -> dict:
    env_force = os.environ.get("FORCE_MODEL_OVERRIDE")
    if env_force:
        body["model"] = env_force
        log.info("Forcing target model to %s via environment override", env_force)
        return body
    if os.environ.get("ALLOW_DEV_MODEL_FORCE", "").lower() in ("1", "true", "yes"):
        force = request.headers.get("x-force-model")
        if force:
            body["model"] = force
            log.info("Forcing target model to %s via header override", force)
    return body
