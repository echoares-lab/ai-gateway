"""
Translation proxy for multiple AI CLI formats → LiteLLM (OpenAI Chat Completions).

Supported client formats:
  Cursor/OpenAI hybrid  POST /v1/chat/completions   (Responses API body → Chat Completions)
  Gemini CLI            POST /v1beta/models/{m}:generateContent[Stream]
  Codex CLI             POST /v1/responses
  Claude CLI            POST /v1/messages

Model prefix (AI-Gateway:) for Cursor model list disambiguation.

Auth normalisation:
  Gemini CLI  ?key=sk-...            → Authorization: Bearer sk-...
  Codex CLI   Authorization: Bearer  → forwarded as-is
  Claude CLI  x-api-key: sk-...      → Authorization: Bearer sk-...
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

import core.metrics  # noqa: F401 — register cache hit/miss counters
import httpx
import redis.asyncio as aioredis
from admin_api import router as admin_router
from api.admin_routes import (
    ADMIN_ERROR_MAXLEN,  # noqa: F401 - re-exported for existing tests
    CLIPROXY_MANAGEMENT_KEY,  # noqa: F401 - re-exported for existing tests
    CLIPROXY_URL,  # noqa: F401 - re-exported for existing tests
    GEMINI_MODEL_MAP_PATH,  # noqa: F401 - re-exported for existing tests
    LITELLM_CONFIG_PATH,  # noqa: F401 - re-exported for existing tests
    AdminRouteDeps,
    _admin_config_drift_panel,  # noqa: F401 - re-exported for existing tests
    _admin_error,  # noqa: F401 - re-exported for existing tests
    _admin_fetch_metrics_text,  # noqa: F401 - re-exported for existing tests
    _admin_fetch_visible_models,  # noqa: F401 - re-exported for existing tests
    _admin_load_litellm_config,  # noqa: F401 - re-exported for existing tests
    _admin_models_panel,  # noqa: F401 - re-exported for existing tests
    _admin_parse_provider_metrics,  # noqa: F401 - re-exported for existing tests
    _admin_policy_engine_connectivity,  # noqa: F401 - re-exported for existing tests
    _admin_redact,
    _admin_routing_panel,  # noqa: F401 - re-exported for existing tests
    _admin_run_readonly_command,  # noqa: F401 - re-exported for existing tests
    _admin_token_analytics_panel,  # noqa: F401 - re-exported for existing tests
    _build_admin_policy_engine_data,  # noqa: F401 - re-exported for existing tests
    _credential_inventory_store,  # noqa: F401 - re-exported for existing tests
    _credential_sync_scheduler_loop,
    _emit_credential_transition_to_policy,  # noqa: F401 - re-exported for existing tests
    _load_model_registry_with_config_fallback,
    _model_registry_store,  # noqa: F401 - re-exported for existing tests
    _record_policy_trace,
    _redact_policy_decision_for_admin,  # noqa: F401 - re-exported for existing tests
    _run_scheduled_credential_sync,  # noqa: F401 - re-exported for existing tests
    configure_admin_routes,
)
from api.admin_routes import (
    router as extracted_admin_router,
)
from api.ws_router import (
    WsRouterDeps,
    _codex_ws_upstream_headers,  # noqa: F401 - re-exported for existing tests
    _parse_ws_client_auth,  # noqa: F401 - re-exported for existing tests
    _policy_engine_enabled,  # noqa: F401 - re-exported for existing tests
    _policy_engine_ws_evaluate_enabled,
    _validate_ws_auth_token,  # noqa: F401 - re-exported for existing tests
    _validate_ws_auth_token_async,  # noqa: F401 - re-exported for existing tests
    _ws_log_safe_mapping,  # noqa: F401 - re-exported for existing tests
    codex_ws_policy_bypass,
    create_ws_router,
)
from core.config import config
from core.credential_inventory import CredentialTransition  # noqa: F401 - re-exported for existing tests
from core.metrics import (
    FORMAT_REQUESTS,
    IN_FLIGHT,
    PROVIDER_LATENCY,
    PROVIDER_RATE_LIMITS,
    PROVIDER_REQUESTS,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    TOKEN_CANONICAL_INPUT,
    TOKEN_CANONICAL_OUTPUT,
    TOKEN_CANONICAL_REQUESTS,
    TOKEN_INPUT,
    TOKEN_OUTPUT,
    TOKEN_REQUESTS,
    UPSTREAM_ERRORS,
)
from core.model_registry import ModelRegistryRecord
from core.policy import PolicyEvaluator
from core.policy import policy_version as in_process_policy_version
from core.policy.client_detector import client_detector
from core.policy.evaluate import process_credential_event_async
from core.policy.schemas import CredentialEvent
from core.state import _policy_history, _policy_trace, record_policy_history
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse
from orchestrator import litellm_admin_get
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from providers import claude as claude_provider
from providers import gemini as gemini_provider
from providers.gemini import get_gemini_map
from providers.virtual import virtual_provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gateway-engine")

UPSTREAM_TIMEOUT = config.UPSTREAM_TIMEOUT
ENABLE_VIRTUAL_PROVIDERS = config.ENABLE_VIRTUAL_PROVIDERS


@asynccontextmanager
async def _lifespan(application: FastAPI):
    global _client, _redis, _policy_evaluator
    credential_sync_task: asyncio.Task | None = None
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(UPSTREAM_TIMEOUT, connect=10.0),
        limits=httpx.Limits(
            max_keepalive_connections=int(os.environ.get("HTTPX_MAX_KEEPALIVE", "20")),
            max_connections=int(os.environ.get("HTTPX_MAX_CONNECTIONS", "100")),
        ),
    )
    redis_url = os.environ.get("REDIS_URL", "")
    if CACHE_ENABLED and redis_url:
        try:
            _redis = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
            await _redis.ping()
            log.info("Redis cache connected: %s", redis_url.split("@")[-1])
        except Exception as exc:
            log.warning("Redis cache unavailable (%s) — caching disabled", exc)
            _redis = None
    if POLICY_ENGINE_ENABLED:
        try:
            _policy_evaluator = PolicyEvaluator.from_env()
            log.info(
                "In-process policy evaluator ready (version=%s)",
                in_process_policy_version(),
            )
        except Exception as exc:
            log.warning("In-process policy evaluator unavailable (%s)", exc)
            _policy_evaluator = None
    if GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED:
        credential_sync_task = asyncio.create_task(_credential_sync_scheduler_loop())
        log.info(
            "gateway-engine credential sync scheduler enabled interval=%ss dry_run=%s",
            GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC,
            GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN,
        )
    yield
    if credential_sync_task is not None:
        credential_sync_task.cancel()
        with suppress(asyncio.CancelledError):
            await credential_sync_task
    if _client is not None:
        await _client.aclose()
    if _redis is not None:
        await _redis.aclose()


app = FastAPI(lifespan=_lifespan)
app.include_router(admin_router)
LITELLM = config.LITELLM_URL
MODEL_PREFIX = "AI-Gateway:"
POLICY_ENGINE_ENABLED = os.environ.get("POLICY_ENGINE_ENABLED", "false").lower() not in (
    "0",
    "false",
    "no",
)
TEAM_BUDGET_SNAPSHOT_ENABLED = os.environ.get("TEAM_BUDGET_SNAPSHOT_ENABLED", "true").lower() not in (
    "0",
    "false",
    "no",
)
TEAM_BUDGET_CACHE_TTL_SEC = int(os.environ.get("TEAM_BUDGET_CACHE_TTL_SEC", "30"))
LITELLM_ADMIN_URL = os.environ.get("LITELLM_ADMIN_URL", LITELLM).rstrip("/")
ADMIN_POLICY_TRACE_ENABLED = os.environ.get("ADMIN_POLICY_TRACE_ENABLED", "true").lower() not in (
    "0",
    "false",
    "no",
)
GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED = os.environ.get(
    "GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED", "false"
).lower() not in (
    "0",
    "false",
    "no",
)
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


_policy_version_hint: str | None = None
_credential_sync_lock = asyncio.Lock()


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


_client: httpx.AsyncClient | None = None
# NOTE: Gateway Engine caching is DISABLED in favor of LiteLLM's auth-aware Redis cache.
# LiteLLM's cache includes Authorization header in its cache key, preventing cross-user responses.
# Gateway Engine caching layer is redundant when multi-team virtual keys are in use.
# Set CACHE_ENABLED=true only if LiteLLM's cache is unavailable or disabled.
CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "false").lower() not in (
    "0",
    "false",
    "no",
)
CACHE_TTL = int(os.environ.get("CACHE_TTL_SECONDS", "60"))
_redis: aioredis.Redis | None = None
_policy_evaluator: PolicyEvaluator | None = None


def _cache_key(model: str, messages: list, tools: list | None = None) -> str | None:
    if not CACHE_ENABLED or _redis is None:
        return None
    key_data: dict = {"m": model, "msgs": messages}
    if tools:
        key_data["tools"] = tools
    digest = hashlib.sha256(json.dumps(key_data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"tx:{digest}"


async def _cache_get(key: str) -> list[str] | None:
    try:
        raw = await _redis.get(key)
        if raw is not None:
            return json.loads(raw)
    except Exception as exc:
        log.debug("cache get error: %s", exc)
    return None


async def _cache_set(key: str, lines: list[str], ttl: int = CACHE_TTL) -> None:
    try:
        await _redis.set(key, json.dumps(lines), ex=ttl)
    except Exception as exc:
        log.debug("cache set error: %s", exc)


async def _aiter_list(lst: list[str]):
    for item in lst:
        yield item


async def _tee_lines(aiter, buf: list[str]):
    async for line in aiter:
        buf.append(line)
        yield line


@app.middleware("http")
async def _limit_request_size(request: Request, call_next):
    """Reject requests larger than MAX_REQUEST_BYTES to prevent memory exhaustion."""
    max_bytes = int(os.environ.get("MAX_REQUEST_BYTES", 50 * 1024 * 1024))  # 50MB default
    if request.headers.get("content-length"):
        try:
            content_length = int(request.headers["content-length"])
            if content_length > max_bytes:
                log.warning("Request too large: %d bytes (limit: %d)", content_length, max_bytes)
                return JSONResponse(
                    {"error": {"message": "request too large", "code": 413}},
                    status_code=413,
                )
        except (ValueError, TypeError):
            pass
    return await call_next(request)


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    req_id = uuid.uuid4().hex[:8]
    request.state.req_id = req_id

    model = "-"
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body_bytes = await request.body()
            model = json.loads(body_bytes).get("model", "-")
        except Exception:
            pass

    log.info("[%s] → %s %s model=%s", req_id, request.method, request.url.path, model)
    IN_FLIGHT.inc()
    _record_format(request.url.path)
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    REQUEST_COUNT.labels(request.method, request.url.path, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, request.url.path).observe(elapsed)
    if response.status_code >= 400:
        UPSTREAM_ERRORS.labels(request.url.path, str(response.status_code)).inc()
    log.info("[%s] ← %d (%.0fms)", req_id, response.status_code, int(elapsed * 1000))
    return response


def _record_format(path: str) -> None:
    p = path.rstrip("/")
    if p in ("v1/messages", "messages"):
        FORMAT_REQUESTS.labels("claude").inc()
    elif p in ("v1/responses", "responses"):
        FORMAT_REQUESTS.labels("responses").inc()
    elif path.startswith("v1beta/models/"):
        FORMAT_REQUESTS.labels("gemini").inc()
    else:
        FORMAT_REQUESTS.labels("proxy").inc()


# Map a (already-resolved) model name to its upstream provider family. Routing
# signals are aggregated per provider so a degraded provider can be deprioritized
# across all its models (see docs/ADAPTIVE_ROUTING.md §2).
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


def _provider_of(model: str) -> str:
    """Derive the provider family from a model name. Returns 'unknown' if unmatched."""
    if not model:
        return "unknown"
    m = model.lower()
    if m.startswith(MODEL_PREFIX.lower()):
        m = m[len(MODEL_PREFIX) :]
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
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if master_key and (not token or token.startswith("ak-")):
        headers[auth_key or "authorization"] = f"Bearer {master_key}"


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
    if model.startswith(MODEL_PREFIX):
        return model[len(MODEL_PREFIX) :]
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
    if _team_alias_index is None or (now - _team_alias_index_at) > TEAM_BUDGET_CACHE_TTL_SEC:
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
    _budget_snapshot_cache[team_alias] = (now + TEAM_BUDGET_CACHE_TTL_SEC, snapshot)
    return snapshot


async def _load_team_budget_snapshot(tenancy: dict) -> dict | None:
    if not TEAM_BUDGET_SNAPSHOT_ENABLED:
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
    requested = model[len("AI-Gateway:") :] if model.startswith("AI-Gateway:") else model
    if not requested:
        return None
    candidates = {requested, requested.replace(".", "-")}
    if requested.startswith("openai/"):
        stripped = requested[len("openai/") :]
        candidates.update({stripped, stripped.replace(".", "-")})
    try:
        loaded = _load_model_registry_with_config_fallback()
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
    if _policy_evaluator is None:
        log.warning("policy evaluate skipped — in-process evaluator not ready")
        _record_policy_trace(None, (time.monotonic() - start) * 1000, error="evaluator unavailable")
        return None
    try:
        decision = await _policy_evaluator.evaluate(context)
        elapsed_ms = (time.monotonic() - start) * 1000
        if decision is None:
            _record_policy_trace(None, elapsed_ms, error="evaluate failed")
            return None
        _record_policy_trace(decision, elapsed_ms)
        return decision
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        log.warning("policy evaluate failed (%s) — fail-open", exc)
        _record_policy_trace(None, elapsed_ms, error=str(exc))
        return None


async def _apply_policy_engine(token: str | None, body: dict) -> dict:
    if not POLICY_ENGINE_ENABLED:
        return body
    tenancy = _tenancy_from_token(token)
    budget = await _load_team_budget_snapshot(tenancy)
    decision = await _evaluate_policy_engine(_build_routing_context(token, body, budget=budget))
    if decision is None:
        return body
    if "metadata" not in body or not isinstance(body["metadata"], dict):
        body["metadata"] = {}
    body["metadata"]["routing_decision"] = decision
    return body


def _record_token_usage(model: str, response_json: dict) -> None:
    """Extract and record token usage from API response for analytics (#117)."""
    provider = _provider_of(model)
    label_model = model or "-"
    try:
        usage = response_json.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        if input_tokens > 0 or output_tokens > 0:
            TOKEN_INPUT.labels(provider, label_model).inc(input_tokens)
            TOKEN_OUTPUT.labels(provider, label_model).inc(output_tokens)
            TOKEN_REQUESTS.labels(provider, label_model).inc()
            registry_metadata = _model_registry_metadata_for_policy(model)
            if registry_metadata:
                canonical_model_id = registry_metadata.get("canonical_model_id") or label_model
                canonical_provider = registry_metadata.get("provider") or provider
                canonical_family = registry_metadata.get("family") or canonical_provider
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
    except (AttributeError, TypeError, KeyError):
        # Safely ignore malformed responses
        pass


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
    rate-limit) for every attempt — see docs/ADAPTIVE_ROUTING.md (issue #59).
    """
    model = _model_from_content(content)

    if ENABLE_VIRTUAL_PROVIDERS and model.startswith("virt-"):
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
        resp = await _client.post(url, headers=headers, content=content)
        _record_provider_signal(model, resp.status_code, time.monotonic() - start)
        if resp.status_code in (502, 503) and attempt < retries:
            log.warning("LiteLLM %d on attempt %d, retrying…", resp.status_code, attempt + 1)
            await asyncio.sleep(1)
            continue
        return resp
    return resp


# ── Shared content normalisation (Responses API / Cursor) ────────────────────


def _normalize_content_item(c: dict) -> dict | None:
    ct = c.get("type", "")
    if ct in ("input_text", "output_text", "text", "refusal"):
        return {"type": "text", "text": c.get("text", c.get("refusal", ""))}
    if ct == "input_image":
        detail = c.get("detail", "auto")
        if "image_url" in c:
            img = c["image_url"]
            if isinstance(img, str):
                img = {"url": img, "detail": detail}
            return {"type": "image_url", "image_url": img}
        if "url" in c:
            return {
                "type": "image_url",
                "image_url": {"url": c["url"], "detail": detail},
            }
        if "source" in c:
            src = c["source"]
            if src.get("type") == "url":
                return {
                    "type": "image_url",
                    "image_url": {"url": src["url"], "detail": detail},
                }
            if src.get("type") == "base64":
                media = src.get("media_type", "image/jpeg")
                return {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media};base64,{src['data']}",
                        "detail": detail,
                    },
                }
        return None
    if ct == "input_file":
        text = c.get("text") or c.get("filename") or "[file]"
        return {"type": "text", "text": text}
    return c


def _normalize_content(content):
    if isinstance(content, str) or content is None:
        return content
    if not isinstance(content, list):
        return str(content)
    normalized = []
    for item in content:
        if isinstance(item, str):
            normalized.append({"type": "text", "text": item})
        elif isinstance(item, dict):
            conv = _normalize_content_item(item)
            if conv is not None:
                normalized.append(conv)
    if all(c.get("type") == "text" for c in normalized):
        return "".join(c.get("text", "") for c in normalized)
    return normalized


def _responses_input_to_messages(inp) -> list:
    if isinstance(inp, str):
        return [{"role": "user", "content": inp}]
    if not isinstance(inp, list):
        return []

    messages = []
    pending_calls: list[dict] = []

    def flush_calls():
        if pending_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": list(pending_calls),
                }
            )
            pending_calls.clear()

    for item in inp:
        if not isinstance(item, dict):
            continue
        t = item.get("type", "")

        if t == "message" or (not t and "role" in item):
            flush_calls()
            role = item.get("role", "user")
            content = item.get("content", "")
            if isinstance(content, list):
                tool_blocks = [
                    c for c in content if isinstance(c, dict) and c.get("type") in ("tool_use", "function_call")
                ]
                if tool_blocks:
                    tool_calls = []
                    text_parts = []
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") in ("tool_use", "function_call"):
                            args = c.get("input", c.get("arguments", {}))
                            tool_calls.append(
                                {
                                    "id": c.get("id", c.get("call_id", "")),
                                    "type": "function",
                                    "function": {
                                        "name": c.get("name", ""),
                                        "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                                    },
                                }
                            )
                        elif c.get("type") in ("text", "input_text", "output_text"):
                            text_parts.append(c.get("text", ""))
                    messages.append(
                        {
                            "role": "assistant",
                            "content": "".join(text_parts) or None,
                            "tool_calls": tool_calls,
                        }
                    )
                    continue
            messages.append({"role": role, "content": _normalize_content(content)})

        elif t == "function_call":
            args = item.get("arguments", "{}")
            pending_calls.append(
                {
                    "id": item.get("id", item.get("call_id", "")),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": args if isinstance(args, str) else json.dumps(args),
                    },
                }
            )

        elif t == "function_call_output":
            flush_calls()
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.get("call_id", item.get("id", "")),
                    "content": str(item.get("output", "")),
                }
            )

    flush_calls()
    return messages


def _normalize_messages(messages: list) -> tuple[list, bool]:
    changed = False
    out = []
    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        content = msg.get("content")
        normed = _normalize_content(content)
        if normed != content:
            changed = True
            msg = {**msg, "content": normed}
        out.append(msg)
    return out, changed


def _normalize_tools(tools: list) -> tuple[list, bool]:
    changed = False
    out = []
    for tool in tools:
        if not isinstance(tool, dict):
            out.append(tool)
            continue
        if tool.get("type") == "function" and "function" not in tool and "name" in tool:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {}),
                    },
                }
            )
            changed = True
        else:
            out.append(tool)
    return out, changed


def _normalize_model(name: str) -> str:
    return name.replace(".", "-")


@dataclass
class _ResolvedModel:
    requested_model: str
    effective_model: str
    change_reason: str
    severity: str
    tool_capability_assumption: str


def _emit_model_resolution(res: _ResolvedModel, endpoint: str, wants_tools: bool) -> None:
    if res.requested_model == res.effective_model and res.severity == "info":
        return
    level = logging.WARNING if res.severity == "warn" else logging.INFO
    log.log(
        level,
        "model_resolution endpoint=%s requested=%s effective=%s reason=%s severity=%s tools=%s assumption=%s",
        endpoint,
        res.requested_model,
        res.effective_model,
        res.change_reason,
        res.severity,
        wants_tools,
        res.tool_capability_assumption,
    )


_PREVIEW_SUFFIX_RE = re.compile(r"-(preview|exp)(-[0-9]{2}-[0-9]{2})?$")


def _maybe_preview_fallback(model: str, wants_tools: bool) -> tuple[str, str, str, str]:
    if not wants_tools:
        return model, "unknown_passthrough", "warn", "native"
    base = _PREVIEW_SUFFIX_RE.sub("", model)
    if base != model:
        return base, "preview_suffix_fallback", "warn", "fallback"
    return model, "unknown_preview_passthrough", "warn", "assumed"


def _resolve_model(
    model: str, endpoint: str, wants_tools: bool = False, gemini_map: dict | None = None
) -> _ResolvedModel:
    requested = model or ""
    effective = requested
    reason = "passthrough"
    severity = "info"
    assumption = "native"

    if effective.startswith(MODEL_PREFIX):
        effective = effective[len(MODEL_PREFIX) :]
        reason = "prefix_strip"

    if endpoint == "gemini":
        base = effective.removesuffix("-customtools")
        if base != effective:
            effective = base
            reason = "customtools_suffix_strip"

        gmap = gemini_map or {}
        mapped = gmap.get(effective)
        if mapped:
            if mapped != effective:
                reason = "gemini_map"
            effective = mapped
        elif "preview" in effective or "exp" in effective:
            effective, reason, severity, assumption = _maybe_preview_fallback(effective, wants_tools)
    else:
        if "." in effective:
            effective = _normalize_model(effective)
            reason = "dotted_to_dashed"
        if ("preview" in effective or "exp" in effective) and endpoint in (
            "responses",
            "chat",
            "claude",
        ):
            # Warn for drift even when unchanged for non-Gemini paths.
            severity = "warn"
            reason = "preview_passthrough"

    res = _ResolvedModel(requested, effective, reason, severity, assumption)
    _emit_model_resolution(res, endpoint, wants_tools)
    return res


def _strip_prefix(body: bytes) -> tuple[bytes, bool]:
    try:
        data = json.loads(body)
    except Exception:
        return body, False
    model = data.get("model", "")
    if isinstance(model, str) and model.startswith(MODEL_PREFIX):
        data["model"] = model[len(MODEL_PREFIX) :]
        return json.dumps(data).encode(), True
    return body, False


def _add_prefix_to_models_response(body: bytes) -> bytes:
    try:
        data = json.loads(body)
    except Exception:
        return body
    if not isinstance(data.get("data"), list):
        return body
    for entry in data["data"]:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            if not entry["id"].startswith(MODEL_PREFIX):
                entry["id"] = MODEL_PREFIX + entry["id"]
    return json.dumps(data).encode()


def _patch_body(path: str, body: bytes) -> tuple[bytes, bool]:
    if path.rstrip("/") not in ("v1/chat/completions", "chat/completions"):
        return body, False
    try:
        data = json.loads(body)
    except Exception:
        return body, False

    changed = False

    if "messages" not in data and "input" in data:
        inp = data.pop("input")
        if isinstance(inp, list):
            log.info(
                "Input item types: %s",
                [i.get("type") if isinstance(i, dict) else type(i).__name__ for i in inp],
            )
        data["messages"] = _responses_input_to_messages(inp)
        n = len(inp) if isinstance(inp, list) else 1
        log.info(
            "Translated Responses API input (%d items) → %d messages",
            n,
            len(data["messages"]),
        )
        changed = True
    elif "messages" in data:
        data["messages"], msg_changed = _normalize_messages(data["messages"])
        if msg_changed:
            log.info("Normalised content types in %d messages", len(data["messages"]))
            changed = True

    if "tools" in data:
        data["tools"], tools_changed = _normalize_tools(data["tools"])
        if tools_changed:
            log.info("Normalised %d tools to Chat Completions format", len(data["tools"]))
            changed = True

    raw_model = data.get("model", "")
    if isinstance(raw_model, str):
        resolved = _resolve_model(raw_model, endpoint="chat", wants_tools=bool(data.get("tools")))
        if resolved.effective_model != raw_model:
            data["model"] = resolved.effective_model
            changed = True

    if changed:
        return json.dumps(data).encode(), True
    return body, False


# ── Gemini format converters (providers.gemini) ──────────────────────────────

_get_gemini_map = get_gemini_map
GEMINI_FINISH_MAP = gemini_provider.FINISH_MAP
_find_tool_call_id_in_history = gemini_provider._find_tool_call_id_in_history


def _gemini_req_to_oai(model: str, body: dict) -> dict:
    return gemini_provider.req_to_oai(model, body, resolve_model=_resolve_model, gemini_map=_get_gemini_map())


def _oai_to_gemini_resp(oai: dict, model: str) -> dict:
    return gemini_provider.oai_to_resp(oai, model)


async def _gemini_stream(oai_lines):
    async for chunk in gemini_provider.stream(oai_lines):
        yield chunk


@app.api_route("/v1beta/models/{model_action:path}", methods=["GET", "POST"])
async def gemini_proxy(model_action: str, request: Request):
    if request.method == "GET":
        # Pass through to LiteLLM (e.g. model info requests)
        resp = await _client.get(
            f"{LITELLM}/v1beta/models/{model_action}",
            params=dict(request.query_params),
            timeout=30,
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"content-type": "application/json"},
        )

    if ":" not in model_action:
        return Response(
            content=json.dumps({"error": {"message": "Invalid path", "code": 400}}),
            status_code=400,
            headers={"content-type": "application/json"},
        )

    model, action = model_action.rsplit(":", 1)
    streaming = action == "streamGenerateContent"

    raw = await request.body()
    try:
        body = json.loads(raw)
    except Exception:
        body = {}

    params = dict(request.query_params)
    api_key = (
        params.pop("key", None)
        or request.headers.get("x-goog-api-key")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or None
    )
    auth = f"Bearer {api_key}" if api_key else ""

    oai_body = _gemini_req_to_oai(model, body)
    if streaming:
        oai_body["stream"] = True

    # Extract and apply tenancy metadata
    oai_body = _extract_and_apply_tenancy(auth, oai_body)
    oai_body = await _apply_policy_engine(auth, oai_body)

    oai_bytes = json.dumps(oai_body).encode()
    headers = {
        "content-type": "application/json",
        "authorization": auth,
        "content-length": str(len(oai_bytes)),
    }

    ck = _cache_key(oai_body.get("model", ""), oai_body.get("messages", []), oai_body.get("tools"))
    log.info(
        "Gemini %s → model=%s tools=%d stream=%s",
        action,
        oai_body["model"],
        len(oai_body.get("tools", [])),
        streaming,
    )

    if streaming:
        req = _client.build_request("POST", f"{LITELLM}/v1/chat/completions", headers=headers, content=oai_bytes)
        try:
            _sig_start = time.monotonic()
            resp = await _client.send(req, stream=True)
            _record_provider_signal(
                oai_body.get("model", "-"),
                resp.status_code,
                time.monotonic() - _sig_start,
            )
        except Exception as exc:
            log.error(
                "Gemini stream connection failed model=%s: %s",
                oai_body.get("model"),
                exc,
            )
            gemini_err = {
                "error": {
                    "code": 502,
                    "message": f"Connection failed: {exc}",
                    "status": "INTERNAL",
                }
            }
            return Response(
                content=json.dumps(gemini_err),
                status_code=502,
                headers={"content-type": "application/json"},
            )

        if resp.status_code >= 400:
            err_content = await resp.aread()
            await resp.aclose()
            log.warning(
                "Gemini upstream stream error %d: %s",
                resp.status_code,
                err_content[:300],
            )
            try:
                err_json = json.loads(err_content)
                err_msg = err_json.get("error", {}).get("message", err_content.decode(errors="ignore"))
            except Exception:
                err_msg = err_content.decode(errors="ignore")
            gemini_err = {
                "error": {
                    "code": resp.status_code,
                    "message": err_msg,
                    "status": "UNAUTHENTICATED" if resp.status_code == 401 else "INTERNAL",
                }
            }
            return Response(
                content=json.dumps(gemini_err),
                status_code=resp.status_code,
                headers={"content-type": "application/json"},
            )

        async def generate():
            if ck:
                cached = await _cache_get(ck)
                if cached is not None:
                    log.info("cache hit (gemini stream) key=%s", ck[:16])
                    await resp.aclose()
                    async for chunk in _gemini_stream(_aiter_list(cached)):
                        yield chunk
                    return
            buf: list[str] = []
            try:
                async for chunk in _gemini_stream(_tee_lines(resp.aiter_lines(), buf)):
                    yield chunk
            except Exception as exc:
                log.error(
                    "Gemini stream upstream error model=%s: %s: %s",
                    oai_body.get("model"),
                    type(exc).__name__,
                    exc,
                )
            finally:
                await resp.aclose()
                if ck and buf:
                    await _cache_set(ck, buf)

        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (gemini) key=%s", ck[:16])
            try:
                return Response(
                    content=json.dumps(_oai_to_gemini_resp(json.loads(cached_json[0]), model)).encode(),
                    status_code=200,
                    headers={"content-type": "application/json"},
                )
            except Exception:
                pass

    resp = await _post_with_retry(f"{LITELLM}/v1/chat/completions", headers, oai_bytes)

    if resp.status_code >= 400:
        log.warning("Gemini upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"content-type": "application/json"},
        )

    try:
        resp_json = resp.json()
        if ck:
            await _cache_set(ck + ":json", [json.dumps(resp_json)])
        # Record token usage for analytics (#117)
        _record_token_usage(model, resp_json)
        gemini_resp = _oai_to_gemini_resp(resp_json, model)
        return Response(
            content=json.dumps(gemini_resp).encode(),
            status_code=200,
            headers={"content-type": "application/json"},
        )
    except Exception as e:
        log.error("Gemini response conversion error: %s", e)
        return Response(content=resp.content, status_code=resp.status_code)


# ── Codex / OpenAI Responses API converters ──────────────────────────────────


def _responses_req_to_oai(body: dict) -> dict:
    messages = []

    instructions = body.get("instructions") or body.get("system")
    if isinstance(instructions, str) and instructions:
        messages.append({"role": "system", "content": instructions})

    inp = body.get("input", "")
    if isinstance(inp, str) and inp:
        messages.append({"role": "user", "content": inp})
    elif isinstance(inp, list):
        messages.extend(_responses_input_to_messages(inp))

    resolved = _resolve_model(body.get("model", ""), endpoint="responses", wants_tools=bool(body.get("tools")))
    oai: dict = {"model": resolved.effective_model, "messages": messages}

    if "max_output_tokens" in body:
        oai["max_tokens"] = body["max_output_tokens"]
    if "temperature" in body:
        oai["temperature"] = body["temperature"]
    if "top_p" in body:
        oai["top_p"] = body["top_p"]

    tools = body.get("tools", [])
    if tools:
        oai["tools"], _ = _normalize_tools(tools)

    tc = body.get("tool_choice")
    if tc:
        oai["tool_choice"] = tc

    return oai


def _oai_to_responses_resp(oai: dict) -> dict:
    choice = oai.get("choices", [{}])[0]
    msg = choice.get("message", {})
    usage = oai.get("usage", {})
    oai_id = oai.get("id", uuid.uuid4().hex)

    output = []

    for tc in msg.get("tool_calls", []):
        fn = tc["function"]
        output.append(
            {
                "type": "function_call",
                "id": tc.get("id", ""),
                "call_id": tc.get("id", ""),
                "name": fn.get("name", ""),
                "arguments": fn.get("arguments", "{}"),
                "status": "completed",
            }
        )

    content = msg.get("content") or ""
    if content or not output:
        output.append(
            {
                "type": "message",
                "id": f"msg_{oai_id}",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content, "annotations": []}],
                "status": "completed",
            }
        )

    return {
        "id": f"resp_{oai_id}",
        "object": "response",
        "created_at": oai.get("created", int(time.time())),
        "status": "completed",
        "model": oai.get("model", ""),
        "output": output,
        "parallel_tool_calls": True,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _oai_to_responses_stream(oai_lines):
    """Convert OpenAI SSE lines to Responses API SSE events."""
    resp_id = f"resp_{uuid.uuid4().hex[:24]}"
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    yield _sse(
        "response.created",
        {
            "type": "response.created",
            "response": {
                "id": resp_id,
                "object": "response",
                "status": "in_progress",
                "output": [],
            },
        },
    )
    yield _sse(
        "response.in_progress",
        {
            "type": "response.in_progress",
            "response": {"id": resp_id, "object": "response", "status": "in_progress"},
        },
    )

    text_started = False
    text_buffer = ""
    tool_buffers: dict[int, dict] = {}  # index → {id, name, args}

    try:
        async for line in oai_lines:
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except Exception:
                continue

            choice = chunk.get("choices", [{}])[0]
            delta = choice.get("delta", {})

            text = delta.get("content", "")
            if text:
                if not text_started:
                    text_started = True
                    yield _sse(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": 0,
                            "item": {
                                "type": "message",
                                "id": msg_id,
                                "role": "assistant",
                                "content": [],
                                "status": "in_progress",
                            },
                        },
                    )
                    yield _sse(
                        "response.content_part.added",
                        {
                            "type": "response.content_part.added",
                            "item_id": msg_id,
                            "output_index": 0,
                            "content_index": 0,
                            "part": {
                                "type": "output_text",
                                "text": "",
                                "annotations": [],
                            },
                        },
                    )
                text_buffer += text
                yield _sse(
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "item_id": msg_id,
                        "output_index": 0,
                        "content_index": 0,
                        "delta": text,
                    },
                )

            for tc_delta in delta.get("tool_calls", []):
                idx = tc_delta.get("index", 0)
                fn = tc_delta.get("function", {})
                if idx not in tool_buffers:
                    tc_id = tc_delta.get("id", f"call_{uuid.uuid4().hex[:24]}")
                    tc_name = fn.get("name", "")
                    tool_buffers[idx] = {"id": tc_id, "name": tc_name, "args": ""}
                    yield _sse(
                        "response.output_item.added",
                        {
                            "type": "response.output_item.added",
                            "output_index": idx,
                            "item": {
                                "type": "function_call",
                                "id": tc_id,
                                "call_id": tc_id,
                                "name": tc_name,
                                "arguments": "",
                                "status": "in_progress",
                            },
                        },
                    )
                if fn.get("name") and not tool_buffers[idx]["name"]:
                    tool_buffers[idx]["name"] = fn["name"]
                if fn.get("arguments"):
                    tool_buffers[idx]["args"] += fn["arguments"]
                    yield _sse(
                        "response.function_call_arguments.delta",
                        {
                            "type": "response.function_call_arguments.delta",
                            "item_id": tool_buffers[idx]["id"],
                            "output_index": idx,
                            "delta": fn["arguments"],
                        },
                    )
    except httpx.HTTPError as exc:
        log.error("Responses stream connection error: %s", exc)

    # Close text
    if text_started:
        yield _sse(
            "response.output_text.done",
            {
                "type": "response.output_text.done",
                "item_id": msg_id,
                "output_index": 0,
                "content_index": 0,
                "text": text_buffer,
            },
        )
        yield _sse(
            "response.content_part.done",
            {
                "type": "response.content_part.done",
                "item_id": msg_id,
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": text_buffer, "annotations": []},
            },
        )
        yield _sse(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "message",
                    "id": msg_id,
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text_buffer, "annotations": []}],
                    "status": "completed",
                },
            },
        )

    # Close tool calls
    for idx, tc in sorted(tool_buffers.items()):
        yield _sse(
            "response.function_call_arguments.done",
            {
                "type": "response.function_call_arguments.done",
                "item_id": tc["id"],
                "output_index": idx,
                "arguments": tc["args"],
            },
        )
        yield _sse(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": idx,
                "item": {
                    "type": "function_call",
                    "id": tc["id"],
                    "call_id": tc["id"],
                    "name": tc["name"],
                    "arguments": tc["args"],
                    "status": "completed",
                },
            },
        )

    yield _sse(
        "response.completed",
        {
            "type": "response.completed",
            "response": {"id": resp_id, "object": "response", "status": "completed"},
        },
    )


@app.post("/v1/responses")
async def responses_proxy(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw)
    except Exception:
        return Response(
            content=json.dumps({"error": "Invalid JSON"}),
            status_code=400,
            headers={"content-type": "application/json"},
        )

    streaming = body.get("stream", False)
    oai_body = _responses_req_to_oai(body)
    if streaming:
        oai_body["stream"] = True

    # Extract and apply tenancy metadata
    auth = request.headers.get("authorization")
    oai_body = _extract_and_apply_tenancy(auth, oai_body)
    oai_body = await _apply_policy_engine(auth, oai_body)

    oai_bytes = json.dumps(oai_body).encode()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length", "content-type")}
    _normalize_upstream_authorization(headers)
    headers["content-type"] = "application/json"
    headers["content-length"] = str(len(oai_bytes))

    ck = _cache_key(oai_body.get("model", ""), oai_body.get("messages", []), oai_body.get("tools"))
    log.info("Codex request headers: %s", {k: v for k, v in request.headers.items()})
    log.info(
        "Codex Responses API → model=%s tools=%d stream=%s",
        oai_body.get("model"),
        len(oai_body.get("tools", [])),
        streaming,
    )

    if streaming:
        req = _client.build_request("POST", f"{LITELLM}/v1/chat/completions", headers=headers, content=oai_bytes)
        try:
            _sig_start = time.monotonic()
            resp = await _client.send(req, stream=True)
            _record_provider_signal(
                oai_body.get("model", "-"),
                resp.status_code,
                time.monotonic() - _sig_start,
            )
        except httpx.TimeoutException as exc:
            log.error("Responses stream upstream timed out: %s", exc)
            err_msg = f"Upstream request timed out after {UPSTREAM_TIMEOUT} seconds. Please check LiteLLM readiness."
            return Response(
                content=json.dumps({"error": {"message": err_msg, "type": "timeout_error"}}),
                status_code=504,
                headers={"content-type": "application/json"},
            )
        except Exception as exc:
            log.error(
                "Responses stream upstream error model=%s: %s",
                oai_body.get("model"),
                exc,
            )
            err_msg = f"Upstream connection failed: {exc}"
            return Response(
                content=json.dumps({"error": {"message": err_msg, "type": "connection_error"}}),
                status_code=502,
                headers={"content-type": "application/json"},
            )

        if resp.status_code >= 400:
            err_content = await resp.aread()
            await resp.aclose()
            log.warning(
                "Responses upstream stream error %d: %s",
                resp.status_code,
                err_content[:300],
            )
            return Response(
                content=err_content,
                status_code=resp.status_code,
                headers={"content-type": "application/json"},
            )

        async def generate():
            if ck:
                cached = await _cache_get(ck)
                if cached is not None:
                    log.info("cache hit (responses stream) key=%s", ck[:16])
                    await resp.aclose()
                    async for event in _oai_to_responses_stream(_aiter_list(cached)):
                        yield event
                    return
            buf: list[str] = []
            try:
                async for event in _oai_to_responses_stream(_tee_lines(resp.aiter_lines(), buf)):
                    yield event
            except httpx.TimeoutException as exc:
                log.error("Responses stream upstream timed out: %s", exc)
                err_id = f"resp_{uuid.uuid4().hex[:24]}"
                err_msg = (
                    f"Upstream request timed out after {UPSTREAM_TIMEOUT} seconds. Please check LiteLLM readiness."
                )
                yield _sse(
                    "error",
                    {
                        "type": "error",
                        "error": {"message": err_msg, "type": "timeout_error"},
                    },
                )
                yield _sse(
                    "response.completed",
                    {
                        "type": "response.completed",
                        "response": {
                            "id": err_id,
                            "object": "response",
                            "status": "failed",
                        },
                    },
                )
            except Exception as exc:
                log.error(
                    "Responses stream upstream error model=%s: %s: %s",
                    oai_body.get("model"),
                    type(exc).__name__,
                    exc,
                )
                err_id = f"resp_{uuid.uuid4().hex[:24]}"
                err_msg = f"Upstream connection failed: {exc}"
                yield _sse(
                    "error",
                    {
                        "type": "error",
                        "error": {"message": err_msg, "type": "connection_error"},
                    },
                )
                yield _sse(
                    "response.completed",
                    {
                        "type": "response.completed",
                        "response": {
                            "id": err_id,
                            "object": "response",
                            "status": "failed",
                        },
                    },
                )
            finally:
                await resp.aclose()
                if ck and buf:
                    await _cache_set(ck, buf)

        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (responses) key=%s", ck[:16])
            try:
                return Response(
                    content=json.dumps(_oai_to_responses_resp(json.loads(cached_json[0]))).encode(),
                    status_code=200,
                    headers={"content-type": "application/json"},
                )
            except Exception:
                pass

    try:
        resp = await _post_with_retry(f"{LITELLM}/v1/chat/completions", headers, oai_bytes)
    except httpx.TimeoutException as exc:
        log.error("Codex upstream request timed out: %s", exc)
        err_msg = f"Upstream request timed out after {UPSTREAM_TIMEOUT} seconds. Please check LiteLLM readiness."
        return Response(
            content=json.dumps({"error": {"message": err_msg, "type": "timeout_error"}}).encode(),
            status_code=504,
            headers={"content-type": "application/json"},
        )
    except Exception as exc:
        log.error("Codex upstream request failed: %s", exc)
        err_msg = f"Upstream connection failed: {exc}"
        return Response(
            content=json.dumps({"error": {"message": err_msg, "type": "connection_error"}}).encode(),
            status_code=502,
            headers={"content-type": "application/json"},
        )

    if resp.status_code >= 400:
        log.warning("Codex upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"content-type": "application/json"},
        )

    try:
        resp_json = resp.json()
        if ck:
            await _cache_set(ck + ":json", [json.dumps(resp_json)])
        # Record token usage for analytics (#117)
        _record_token_usage(oai_body.get("model", "-"), resp_json)
        responses_resp = _oai_to_responses_resp(resp_json)
        return Response(
            content=json.dumps(responses_resp).encode(),
            status_code=200,
            headers={"content-type": "application/json"},
        )
    except Exception as e:
        log.error("Codex response conversion error: %s", e)
        return Response(content=resp.content, status_code=resp.status_code)


# ── Claude / Anthropic Messages API converters (providers.claude) ──────────────


def _claude_msg_to_oai(msg: dict) -> list[dict]:
    return claude_provider.msg_to_oai(msg)


def _claude_req_to_oai(body: dict) -> dict:
    return claude_provider.req_to_oai(body, resolve_model=_resolve_model)


def _oai_to_claude_resp(oai: dict) -> dict:
    return claude_provider.oai_to_resp(oai)


async def _oai_to_claude_stream(oai_lines, model: str):
    async for event in claude_provider.stream(oai_lines, model):
        yield event


@app.post("/v1/messages")
async def claude_proxy(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw)
    except Exception:
        return Response(
            content=json.dumps({"error": {"type": "invalid_request_error", "message": "Invalid JSON"}}),
            status_code=400,
            headers={"content-type": "application/json"},
        )

    streaming = body.get("stream", False)
    oai_body = _claude_req_to_oai(body)
    if streaming:
        oai_body["stream"] = True

    api_key = (
        request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    )
    # Extract and apply tenancy metadata
    oai_body = _extract_and_apply_tenancy(api_key, oai_body)
    oai_body = await _apply_policy_engine(api_key, oai_body)

    oai_bytes = json.dumps(oai_body).encode()
    headers = {
        "content-type": "application/json",
        "content-length": str(len(oai_bytes)),
    }
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"

    model = oai_body.get("model", "")
    ck = _cache_key(model, oai_body.get("messages", []), oai_body.get("tools"))
    log.info(
        "Claude Messages API → model=%s tools=%d stream=%s",
        model,
        len(oai_body.get("tools", [])),
        streaming,
    )

    if streaming:
        req = _client.build_request("POST", f"{LITELLM}/v1/chat/completions", headers=headers, content=oai_bytes)
        try:
            _sig_start = time.monotonic()
            resp = await _client.send(req, stream=True)
            _record_provider_signal(
                oai_body.get("model", "-"),
                resp.status_code,
                time.monotonic() - _sig_start,
            )
        except Exception as exc:
            log.error(
                "Claude stream connection failed model=%s: %s",
                oai_body.get("model"),
                exc,
            )
            return Response(
                content=json.dumps(
                    {
                        "error": {
                            "type": "api_error",
                            "message": f"Connection failed: {exc}",
                        }
                    }
                ),
                status_code=502,
                headers={"content-type": "application/json"},
            )

        if resp.status_code >= 400:
            err_content = await resp.aread()
            await resp.aclose()
            log.warning(
                "Claude upstream stream error %d: %s",
                resp.status_code,
                err_content[:300],
            )
            return Response(
                content=err_content,
                status_code=resp.status_code,
                headers={"content-type": "application/json"},
            )

        async def generate():
            if ck:
                cached = await _cache_get(ck)
                if cached is not None:
                    log.info("cache hit (claude stream) key=%s", ck[:16])
                    await resp.aclose()
                    async for event in _oai_to_claude_stream(_aiter_list(cached), model):
                        yield event
                    return
            buf: list[str] = []
            try:
                async for event in _oai_to_claude_stream(_tee_lines(resp.aiter_lines(), buf), model):
                    yield event
            except Exception as exc:
                log.error(
                    "Claude stream upstream error model=%s: %s: %s",
                    oai_body.get("model"),
                    type(exc).__name__,
                    exc,
                )
                msg_id = f"msg_{uuid.uuid4().hex[:24]}"
                yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'stop_reason': 'end_turn', 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
                yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
            finally:
                await resp.aclose()
                if ck and buf:
                    await _cache_set(ck, buf)

        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (claude) key=%s", ck[:16])
            try:
                return Response(
                    content=json.dumps(_oai_to_claude_resp(json.loads(cached_json[0]))).encode(),
                    status_code=200,
                    headers={"content-type": "application/json"},
                )
            except Exception:
                pass

    resp = await _post_with_retry(f"{LITELLM}/v1/chat/completions", headers, oai_bytes)

    if resp.status_code >= 400:
        log.warning("Claude upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers={"content-type": "application/json"},
        )

    try:
        resp_json = resp.json()
        if ck:
            await _cache_set(ck + ":json", [json.dumps(resp_json)])
        # Record token usage for analytics (#117)
        _record_token_usage(model, resp_json)
        claude_resp = _oai_to_claude_resp(resp_json)
        return Response(
            content=json.dumps(claude_resp).encode(),
            status_code=200,
            headers={"content-type": "application/json"},
        )
    except Exception as e:
        log.error("Claude response conversion error: %s", e)
        return Response(content=resp.content, status_code=resp.status_code)


@app.get("/health")
async def health():
    return {"status": "ok"}


def _policy_mock_scenarios_enabled() -> bool:
    return os.environ.get("POLICY_MOCK_SCENARIOS", "").lower() in ("1", "true", "yes")


@app.get("/debug/policy/last")
async def debug_policy_last():
    """Gate B: last in-process mock evaluate payload (mock tier only)."""
    if not _policy_mock_scenarios_enabled():
        return JSONResponse(status_code=404, content={"detail": "not available"})
    from core.policy.mock_scenarios import last_evaluate_payload

    return last_evaluate_payload() or {}


@app.post("/debug/policy/reset")
async def debug_policy_reset():
    if not _policy_mock_scenarios_enabled():
        return JSONResponse(status_code=404, content={"detail": "not available"})
    from core.policy.mock_scenarios import reset_mock_scenarios

    reset_mock_scenarios()
    return {"ok": True}


configure_admin_routes(
    AdminRouteDeps(
        get_http_client=lambda: _client,
        get_redis=lambda: _redis,
        provider_of=_provider_of,
        process_credential_event=lambda event: process_credential_event_async(event),
        admin_policy_trace_enabled=lambda: ADMIN_POLICY_TRACE_ENABLED,
        policy_engine_enabled=lambda: POLICY_ENGINE_ENABLED,
        policy_engine_ws_evaluate_enabled=_policy_engine_ws_evaluate_enabled,
        codex_ws_policy_bypass=codex_ws_policy_bypass,
        policy_history=_policy_history,
        policy_trace=_policy_trace,
        record_policy_history=record_policy_history,
        litellm_url=LITELLM,
        model_prefix=MODEL_PREFIX,
    )
)
app.include_router(extracted_admin_router)


# ── Catch-all proxy (Cursor / generic OpenAI-compatible clients) ─────────────


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    raw = await request.body()

    body, prefix_stripped = _strip_prefix(raw)
    body, fmt_changed = _patch_body(path, body if prefix_stripped else raw)
    if not fmt_changed and not prefix_stripped:
        body = raw
    changed = prefix_stripped or fmt_changed

    integration_profile = client_detector.detect(request)
    log.debug(
        "Detected integration profile: %s",
        integration_profile.get("client_name") if integration_profile else "none",
    )

    # Intercept /responses/compact for non-OpenAI models: map to gpt-5-5 for CLIProxy compatibility
    is_responses_compact = path.rstrip("/") in (
        "v1/responses/compact",
        "responses/compact",
    )
    if is_responses_compact and request.method == "POST":
        try:
            bd = json.loads(body)
            model = bd.get("model", "")
            # Map non-OpenAI models (Claude, Gemini, etc.) to gpt-5-5 for native /responses/compact support
            if model and not model.startswith("gpt-") and not model.startswith("o1-") and not model.startswith("o3-"):
                log.info(
                    "Responses/compact interception: mapping model %s to gpt-5-5 for CLIProxy compatibility",
                    model,
                )
                bd["model"] = "gpt-5-5"
                body = json.dumps(bd).encode()
                changed = True
        except Exception as e:
            log.debug("Failed to intercept /responses/compact: %s", e)

    # Extract and apply tenancy metadata for all POST requests
    if request.method == "POST":
        try:
            bd = json.loads(body)
            auth_token = request.headers.get("authorization", "")
            bd = _extract_and_apply_tenancy(auth_token, bd)
            bd = await _apply_policy_engine(auth_token, bd)
            body = json.dumps(bd).encode()
            changed = True
        except Exception:
            pass

    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}

    if integration_profile and "inject_headers" in integration_profile.get("config", {}):
        headers.update(integration_profile["config"]["inject_headers"])

    _normalize_upstream_authorization(headers)
    log.info(
        "Proxy request path: %s headers: %s",
        path,
        {k: v for k, v in headers.items() if k.lower() != "authorization"},
    )
    if changed:
        headers["content-length"] = str(len(body))

    is_stream = False
    try:
        is_stream = json.loads(body).get("stream", False)
    except Exception:
        pass

    url = f"{LITELLM}/{path}"
    params = dict(request.query_params)

    # Cache only chat completion POST requests
    ck = None
    is_chat = path.rstrip("/") in ("v1/chat/completions", "chat/completions")
    if is_chat and request.method == "POST":
        try:
            bd = json.loads(body)
            ck = _cache_key(bd.get("model", ""), bd.get("messages", []), bd.get("tools"))
        except Exception:
            pass

    signal_model = _model_from_content(body) if is_chat else ""

    if is_stream:

        async def generate():
            if ck:
                cached = await _cache_get(ck)
                if cached is not None:
                    log.info("cache hit (proxy stream) key=%s", ck[:16])
                    for line in cached:
                        yield (line + "\n").encode()
                    return
            buf: list[str] = []
            start = time.monotonic()
            try:
                async with _client.stream(request.method, url, headers=headers, content=body, params=params) as resp:
                    if is_chat:
                        _record_provider_signal(signal_model, resp.status_code, time.monotonic() - start)
                    async for chunk in resp.aiter_bytes():
                        if ck:
                            buf.append(chunk.decode(errors="replace"))
                        yield chunk
            except httpx.TimeoutException as exc:
                log.error("Proxy stream upstream timed out for %s: %s", path, exc)
                err = {
                    "error": {
                        "message": f"Upstream request timed out after {UPSTREAM_TIMEOUT} seconds",
                        "type": "timeout_error",
                    }
                }
                yield ("data: " + json.dumps(err) + "\n\n").encode()
            except Exception as exc:
                log.error("Proxy stream upstream error for %s: %s", path, exc)
                err = {
                    "error": {
                        "message": f"Upstream connection failed: {exc}",
                        "type": "connection_error",
                    }
                }
                yield ("data: " + json.dumps(err) + "\n\n").encode()
            if ck and buf:
                await _cache_set(ck, buf)

        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (proxy) key=%s", ck[:16])
            return Response(
                content=cached_json[0].encode(),
                status_code=200,
                headers={"content-type": "application/json"},
            )

    _proxy_start = time.monotonic()

    if ENABLE_VIRTUAL_PROVIDERS and signal_model.startswith("virt-"):
        parts = signal_model.split("-")
        status_code = 200
        if len(parts) >= 3 and parts[1] == "error":
            try:
                status_code = int(parts[2])
            except ValueError:
                pass

        try:
            req_body = json.loads(body)
        except Exception:
            req_body = {}

        if status_code == 200:
            v_resp = virtual_provider.oai_to_resp(req_body, signal_model)
        else:
            v_resp = virtual_provider.simulate_error(status_code)

        elapsed = time.monotonic() - _proxy_start
        if is_chat:
            _record_provider_signal(signal_model, status_code, elapsed)

        resp_body = json.dumps(v_resp).encode("utf-8")
        if ck and status_code == 200 and is_chat:
            await _cache_set(ck + ":json", [resp_body.decode("utf-8")])

        return Response(content=resp_body, status_code=status_code, headers={"content-type": "application/json"})

    try:
        resp = await _client.request(request.method, url, headers=headers, content=body, params=params)
    except httpx.TimeoutException as exc:
        log.error("Proxy upstream timed out for %s: %s", path, exc)
        return Response(
            content=json.dumps(
                {
                    "error": {
                        "message": f"Upstream request timed out after {UPSTREAM_TIMEOUT} seconds",
                        "type": "timeout_error",
                    }
                }
            ).encode(),
            status_code=504,
            headers={"content-type": "application/json"},
        )
    except Exception as exc:
        log.error("Proxy upstream connection failed for %s: %s", path, exc)
        return Response(
            content=json.dumps(
                {
                    "error": {
                        "message": f"Upstream connection failed: {exc}",
                        "type": "connection_error",
                    }
                }
            ).encode(),
            status_code=502,
            headers={"content-type": "application/json"},
        )
    if is_chat:
        _record_provider_signal(signal_model, resp.status_code, time.monotonic() - _proxy_start)

    if resp.status_code >= 400:
        log.warning(
            "Upstream %d for %s — raw: %s",
            resp.status_code,
            path,
            raw[:600].decode(errors="replace"),
        )

    if ck and resp.status_code == 200 and is_chat:
        await _cache_set(ck + ":json", [resp.text])

    resp_body = resp.content
    resp_headers = dict(resp.headers)

    if path.rstrip("/") in ("v1/models", "models") and resp.status_code == 200:
        resp_body = _add_prefix_to_models_response(resp_body)
        resp_headers["content-length"] = str(len(resp_body))

    return Response(content=resp_body, status_code=resp.status_code, headers=resp_headers)


def _build_ws_routing_context(ws: WebSocket, token: str) -> dict:
    """Build routing context for WebSocket requests (issue 182)."""
    return {
        "requested_model": ws.query_params.get("model", "codex"),
        "tenancy": _tenancy_from_token(token),
        "protocol": "ws",
    }


app.include_router(
    create_ws_router(
        WsRouterDeps(
            admin_redact=_admin_redact,
            build_routing_context=_build_ws_routing_context,
            evaluate_policy_engine=_evaluate_policy_engine,
            upstream_timeout=UPSTREAM_TIMEOUT,
        )
    )
)


@app.post("/v1/events/credential")
async def handle_policy_credential_event(event: CredentialEvent):
    """Handle external credential events (cooldowns/prober) in-process (issue 183)."""
    await process_credential_event_async(event)
    return {"accepted": True}
