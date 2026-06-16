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
import time
import uuid
from contextlib import asynccontextmanager, suppress

import core.metrics  # noqa: F401 — register cache hit/miss counters
import httpx
import redis.asyncio as aioredis
from admin_api import router as admin_router
from api import proxy_router as proxy_routes
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
    REQUEST_COUNT,
    REQUEST_LATENCY,
    UPSTREAM_ERRORS,
)
from core.policy import PolicyEvaluator
from core.policy import policy_version as in_process_policy_version
from core.policy.evaluate import process_credential_event_async
from core.policy.schemas import CredentialEvent
from core.state import _policy_history, _policy_trace, record_policy_history
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

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

ProxyRouterDeps = proxy_routes.ProxyRouterDeps
configure_proxy_routes = proxy_routes.configure_proxy_routes
proxy_router = proxy_routes.router

_provider_of = proxy_routes._provider_of
_model_from_content = proxy_routes._model_from_content
_outcome_for_status = proxy_routes._outcome_for_status
_quota_headroom_cache = proxy_routes._quota_headroom_cache
PROVIDER_LATENCY = proxy_routes.PROVIDER_LATENCY
PROVIDER_RATE_LIMITS = proxy_routes.PROVIDER_RATE_LIMITS
PROVIDER_REQUESTS = proxy_routes.PROVIDER_REQUESTS
TOKEN_CANONICAL_INPUT = proxy_routes.TOKEN_CANONICAL_INPUT
TOKEN_CANONICAL_OUTPUT = proxy_routes.TOKEN_CANONICAL_OUTPUT
TOKEN_CANONICAL_REQUESTS = proxy_routes.TOKEN_CANONICAL_REQUESTS
TOKEN_INPUT = proxy_routes.TOKEN_INPUT
TOKEN_OUTPUT = proxy_routes.TOKEN_OUTPUT
TOKEN_REQUESTS = proxy_routes.TOKEN_REQUESTS
_tenancy_from_token = proxy_routes._tenancy_from_token
_extract_and_apply_tenancy = proxy_routes._extract_and_apply_tenancy
_normalize_upstream_authorization = proxy_routes._normalize_upstream_authorization
_record_token_usage = proxy_routes._record_token_usage
_record_provider_signal = proxy_routes._record_provider_signal
_post_with_retry = proxy_routes._post_with_retry
_aiter_list = proxy_routes._aiter_list
_tee_lines = proxy_routes._tee_lines
_normalize_content_item = proxy_routes._normalize_content_item
_normalize_content = proxy_routes._normalize_content
_responses_input_to_messages = proxy_routes._responses_input_to_messages
_normalize_messages = proxy_routes._normalize_messages
_normalize_tools = proxy_routes._normalize_tools
_normalize_model = proxy_routes._normalize_model
_ResolvedModel = proxy_routes._ResolvedModel
_resolve_model = proxy_routes._resolve_model
_strip_prefix = proxy_routes._strip_prefix
_add_prefix_to_models_response = proxy_routes._add_prefix_to_models_response
_patch_body = proxy_routes._patch_body
_get_gemini_map = proxy_routes._get_gemini_map
GEMINI_FINISH_MAP = proxy_routes.GEMINI_FINISH_MAP
_find_tool_call_id_in_history = proxy_routes._find_tool_call_id_in_history
_gemini_req_to_oai = proxy_routes._gemini_req_to_oai
_oai_to_gemini_resp = proxy_routes._oai_to_gemini_resp
_gemini_stream = proxy_routes._gemini_stream
gemini_proxy = proxy_routes.gemini_proxy
_responses_req_to_oai = proxy_routes._responses_req_to_oai
_oai_to_responses_resp = proxy_routes._oai_to_responses_resp
_sse = proxy_routes._sse
_oai_to_responses_stream = proxy_routes._oai_to_responses_stream
responses_proxy = proxy_routes.responses_proxy
_claude_msg_to_oai = proxy_routes._claude_msg_to_oai
_claude_req_to_oai = proxy_routes._claude_req_to_oai
_oai_to_claude_resp = proxy_routes._oai_to_claude_resp
_oai_to_claude_stream = proxy_routes._oai_to_claude_stream
claude_proxy = proxy_routes.claude_proxy
proxy = proxy_routes.proxy
_build_routing_context = proxy_routes._build_routing_context
_evaluate_policy_engine = proxy_routes._evaluate_policy_engine
_apply_policy_engine = proxy_routes._apply_policy_engine
_model_registry_metadata_for_policy = proxy_routes._model_registry_metadata_for_policy
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

configure_proxy_routes(
    ProxyRouterDeps(
        get_http_client=lambda: _client,
        get_policy_evaluator=lambda: _policy_evaluator,
        cache_key=_cache_key,
        cache_get=_cache_get,
        cache_set=_cache_set,
        record_policy_trace=_record_policy_trace,
        load_model_registry=_load_model_registry_with_config_fallback,
        litellm_url=LITELLM,
        model_prefix=MODEL_PREFIX,
        upstream_timeout=UPSTREAM_TIMEOUT,
        enable_virtual_providers=lambda: ENABLE_VIRTUAL_PROVIDERS,
        policy_engine_enabled=lambda: POLICY_ENGINE_ENABLED,
        team_budget_snapshot_enabled=lambda: TEAM_BUDGET_SNAPSHOT_ENABLED,
        team_budget_cache_ttl_sec=TEAM_BUDGET_CACHE_TTL_SEC,
    )
)
app.include_router(proxy_router)


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
