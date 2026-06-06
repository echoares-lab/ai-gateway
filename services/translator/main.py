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
import subprocess
import time
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone

import core.metrics  # noqa: F401 — register cache hit/miss counters
import httpx
import redis.asyncio as aioredis
import websockets
import yaml
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
from core.model_registry import (
    ModelProbeResponse,
    ModelRegistryListResponse,
    ModelRegistryMutationResponse,
    ModelRegistryPatchRequest,
    ModelRegistryReconcileRequest,
    ModelRegistryReconcileResponse,
    ModelRegistryRecord,
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
from core.policy.evaluate import process_credential_event_async
from core.policy.schemas import CredentialEvent
from core.state import _policy_trace
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from providers import claude as claude_provider
from providers import gemini as gemini_provider
from providers.gemini import get_gemini_map

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("translator")

UPSTREAM_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "30.0"))


@asynccontextmanager
async def _lifespan(application: FastAPI):
    global _client, _redis
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
    if TRANSLATOR_CREDENTIAL_SYNC_ENABLED:
        credential_sync_task = asyncio.create_task(_credential_sync_scheduler_loop())
        log.info(
            "translator credential sync scheduler enabled interval=%ss dry_run=%s",
            TRANSLATOR_CREDENTIAL_SYNC_INTERVAL_SEC,
            TRANSLATOR_CREDENTIAL_SYNC_DRY_RUN,
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
LITELLM = os.environ.get("LITELLM_URL", "http://litellm:4000")
MODEL_PREFIX = "AI-Gateway:"
POLICY_ENGINE_ENABLED = os.environ.get("POLICY_ENGINE_ENABLED", "false").lower() not in (
    "0",
    "false",
    "no",
)
POLICY_ENGINE_URL = os.environ.get("POLICY_ENGINE_URL", "http://policy-engine:8080").rstrip("/")
POLICY_ENGINE_TIMEOUT_MS = int(os.environ.get("POLICY_ENGINE_TIMEOUT_MS", "100"))
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
TRANSLATOR_CREDENTIAL_SYNC_ENABLED = os.environ.get("TRANSLATOR_CREDENTIAL_SYNC_ENABLED", "false").lower() not in (
    "0",
    "false",
    "no",
)
TRANSLATOR_CREDENTIAL_SYNC_INTERVAL_SEC = max(
    1,
    int(os.environ.get("TRANSLATOR_CREDENTIAL_SYNC_INTERVAL_SEC", "300")),
)
TRANSLATOR_CREDENTIAL_SYNC_INITIAL_DELAY_SEC = max(
    0,
    int(os.environ.get("TRANSLATOR_CREDENTIAL_SYNC_INITIAL_DELAY_SEC", "30")),
)
TRANSLATOR_CREDENTIAL_SYNC_DRY_RUN = os.environ.get("TRANSLATOR_CREDENTIAL_SYNC_DRY_RUN", "false").lower() not in (
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
# NOTE: Translator caching is DISABLED in favor of LiteLLM's auth-aware Redis cache.
# LiteLLM's cache includes Authorization header in its cache key, preventing cross-user responses.
# Translator caching layer is redundant when multi-team virtual keys are in use.
# Set CACHE_ENABLED=true only if LiteLLM's cache is unavailable or disabled.
CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "false").lower() not in (
    "0",
    "false",
    "no",
)
CACHE_TTL = int(os.environ.get("CACHE_TTL_SECONDS", "60"))
_redis: aioredis.Redis | None = None


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
        await _redis.setex(key, ttl, json.dumps(lines))
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


async def _litellm_admin_get(path: str, *, params: dict | None = None) -> dict | None:
    if _client is None:
        return None
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not master_key:
        return None
    headers = {"Authorization": f"Bearer {master_key}"}
    try:
        resp = await _client.get(
            f"{LITELLM_ADMIN_URL}{path}",
            headers=headers,
            params=params,
            timeout=0.25,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception:
        return None


async def _resolve_litellm_team_id(team_alias: str) -> str | None:
    global _team_alias_index, _team_alias_index_at
    now = time.monotonic()
    if _team_alias_index is None or (now - _team_alias_index_at) > TEAM_BUDGET_CACHE_TTL_SEC:
        data = await _litellm_admin_get("/team/list")
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
    data = await _litellm_admin_get("/team/info", params={"team_id": team_id})
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
    """POST /v1/evaluate; fail-open on timeout or error."""
    start = time.monotonic()
    if _client is None:
        log.warning("policy-engine evaluate skipped — httpx client not ready")
        _record_policy_trace(None, (time.monotonic() - start) * 1000, error="client unavailable")
        return None
    url = f"{POLICY_ENGINE_URL}/v1/evaluate"
    timeout = POLICY_ENGINE_TIMEOUT_MS / 1000.0
    try:
        resp = await _client.post(url, json={"context": context}, timeout=timeout)
        elapsed_ms = (time.monotonic() - start) * 1000
        if resp.status_code != 200:
            log.warning(
                "policy-engine evaluate returned %d — fail-open: %s",
                resp.status_code,
                resp.text[:200],
            )
            _record_policy_trace(None, elapsed_ms, error=f"http {resp.status_code}")
            return None
        decision = resp.json().get("decision")
        if not isinstance(decision, dict):
            log.warning("policy-engine response missing decision — fail-open")
            _record_policy_trace(None, elapsed_ms, error="missing decision")
            return None
        _record_policy_trace(decision, elapsed_ms)
        return decision
    except httpx.TimeoutException:
        elapsed_ms = (time.monotonic() - start) * 1000
        log.warning(
            "policy-engine evaluate timed out after %dms — fail-open",
            POLICY_ENGINE_TIMEOUT_MS,
        )
        _record_policy_trace(None, elapsed_ms, error="timeout")
        return None
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        log.warning("policy-engine evaluate failed (%s) — fail-open", exc)
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


# ── Codex WebSocket policy (issue 38-14) ─────────────────────────────────────
# WS /v1/responses proxies directly to CLIProxy; see POLICY_ENGINE_AND_ROUTING_REFACTOR.md §9.


def _policy_engine_enabled() -> bool:
    return os.environ.get("POLICY_ENGINE_ENABLED", "").lower() in ("1", "true", "yes")


def _policy_engine_ws_evaluate_enabled() -> bool:
    return os.environ.get("POLICY_ENGINE_WS_EVALUATE", "").lower() in (
        "1",
        "true",
        "yes",
    )


def codex_ws_policy_bypass() -> bool:
    """True when Codex WS upgrade skips policy-engine evaluate (default).

    Optional parity requires both POLICY_ENGINE_ENABLED and POLICY_ENGINE_WS_EVALUATE
    (translator integration issue 38-04 must ship evaluate wiring first).
    """
    if _policy_engine_enabled() and _policy_engine_ws_evaluate_enabled():
        return False
    return True


def _codex_ws_upstream_headers(
    ws_headers: dict[str, str],
    routing_decision: dict | None = None,
) -> dict[str, str]:
    """Build CLIProxy upstream handshake headers for Codex WebSocket proxy."""
    skip = {
        "host",
        "upgrade",
        "connection",
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
        "sec-websocket-protocol",
        "content-length",
    }
    headers = {k: v for k, v in ws_headers.items() if k.lower() not in skip}

    cliproxy_api_key = os.environ.get("CLIPROXY_API_KEY", "")
    if cliproxy_api_key:
        headers["authorization"] = f"Bearer {cliproxy_api_key}"

    if routing_decision:
        session_key = routing_decision.get("session_key")
        if session_key:
            headers["x-session-id"] = session_key
        if routing_decision.get("quota_aware_mode"):
            headers["x-quota-aware-mode"] = "true"
        deprioritized = routing_decision.get("deprioritized_credentials") or []
        if deprioritized:
            headers["x-deprioritized-credentials"] = ",".join(str(c) for c in deprioritized)

    return headers


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


@app.websocket("/v1/responses")
async def responses_websocket(ws: WebSocket):
    # Accept client WebSocket connection
    await ws.accept()

    log.info("WebSocket headers: %s", dict(ws.headers))
    log.info("WebSocket query params: %s", dict(ws.query_params))

    # Authenticate client connection
    client_auth = ws.headers.get("authorization", "")
    if not client_auth:
        client_auth = ws.headers.get("api-key", "")
    if not client_auth:
        client_auth = ws.query_params.get("key", "")

    expected_master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    is_authorized = True

    if client_auth:
        auth_token = client_auth
        if auth_token.startswith("Bearer "):
            auth_token = auth_token[7:]

        if expected_master_key and auth_token == expected_master_key:
            is_authorized = True
        elif auth_token.startswith("sk-") and len(auth_token) >= 10:
            is_authorized = True
        else:
            is_authorized = False

    if not is_authorized:
        log.warning(
            "Unauthorized Codex WebSocket connection attempt with token: %s",
            client_auth,
        )
        try:
            await ws.close(code=1008, reason="Unauthorized")
        except Exception:
            pass
        return

    # Target CLIProxy WebSocket URL
    cliproxy_ws_url = os.environ.get("CLIPROXY_WS_URL", "ws://cliproxy:8317/v1/responses")

    ws_bypass = codex_ws_policy_bypass()
    routing_decision = None
    if ws_bypass:
        log.info(
            "Codex WebSocket policy bypass active (direct CLIProxy proxy); "
            "set POLICY_ENGINE_WS_EVALUATE=true with POLICY_ENGINE_ENABLED for optional evaluate"
        )
    else:
        log.info("Codex WebSocket policy evaluate requested — awaiting 38-04 translator wiring")

    headers = _codex_ws_upstream_headers(dict(ws.headers), routing_decision)

    log.info(
        "Proxying Codex WebSocket to upstream: %s (policy_bypass=%s)",
        cliproxy_ws_url,
        ws_bypass,
    )
    try:
        # Determine whether to use additional_headers or extra_headers
        import inspect

        connect_sig = inspect.signature(websockets.connect)
        connect_kwargs = {}
        if "additional_headers" in connect_sig.parameters:
            connect_kwargs["additional_headers"] = headers
        else:
            connect_kwargs["extra_headers"] = headers

        async with websockets.connect(cliproxy_ws_url, **connect_kwargs) as upstream:

            async def client_to_upstream():
                try:
                    while True:
                        data = await ws.receive()
                        if data.get("type") == "websocket.disconnect":
                            break

                        text = data.get("text")
                        if text is not None:
                            await upstream.send(text)
                            continue

                        bytes_data = data.get("bytes")
                        if bytes_data is not None:
                            await upstream.send(bytes_data)
                            continue
                except Exception as exc:
                    log.debug("Codex WebSocket client_to_upstream error: %s", exc)

            async def upstream_to_client():
                try:
                    received_any = False
                    while True:
                        try:
                            timeout_val = UPSTREAM_TIMEOUT if not received_any else 15.0
                            message = await asyncio.wait_for(upstream.recv(), timeout=timeout_val)
                            received_any = True
                            if isinstance(message, str):
                                await ws.send_text(message)
                            elif isinstance(message, bytes):
                                await ws.send_bytes(message)
                        except asyncio.TimeoutError:
                            log.warning("Codex WebSocket upstream read timed out")
                            err_msg = {
                                "type": "error",
                                "error": {
                                    "message": f"Upstream WebSocket connection timed out after {UPSTREAM_TIMEOUT}s.",
                                    "type": "timeout_error",
                                },
                            }
                            await ws.send_text(json.dumps(err_msg))
                            await ws.close(code=1011, reason="Upstream timeout")
                            break
                except Exception as exc:
                    log.debug("Codex WebSocket upstream_to_client error: %s", exc)

            t1 = asyncio.create_task(client_to_upstream())
            t2 = asyncio.create_task(upstream_to_client())
            done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
    except Exception as exc:
        log.error(
            "Failed to connect or proxy Codex WebSocket to upstream %s: %s",
            cliproxy_ws_url,
            exc,
        )
        try:
            await ws.close(code=1011, reason=f"Upstream connection failed: {exc}")
        except Exception:
            pass


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


# ── Read-only admin status aggregator (issue #69) ─────────────────────────────
# Emits the admin-console.v1 contract (see docs/ADMIN_CONSOLE_DATA_CONTRACT.md).
# Read-only and operator-local by design: it never mutates state, bounds every
# external/subprocess source, and redacts secrets. A failed source degrades its
# panel to warning/unknown rather than failing the whole response.

ADMIN_SCHEMA_VERSION = "admin-console.v1"
LITELLM_CONFIG_PATH = os.environ.get("LITELLM_CONFIG_PATH", "/config/litellm-config.yaml")
GEMINI_MODEL_MAP_PATH = os.environ.get("GEMINI_MODEL_MAP_PATH", "/app/gemini-model-map.json")
ADMIN_ERROR_MAXLEN = 400
TRANSLATOR_ADMIN_KEY = os.environ.get("TRANSLATOR_ADMIN_KEY", "")
CLIPROXY_URL = os.environ.get("CLIPROXY_URL", "http://cliproxy:8317").rstrip("/")
CLIPROXY_MANAGEMENT_KEY = os.environ.get("CLIPROXY_MANAGEMENT_KEY", "")
MODEL_PROBE_TIMEOUT = float(os.environ.get("MODEL_PROBE_TIMEOUT", "8.0"))

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


def _admin_key_valid(request: Request) -> bool:
    """Return true when mutating translator admin APIs are enabled and authorized."""
    configured = TRANSLATOR_ADMIN_KEY or os.environ.get("TRANSLATOR_ADMIN_KEY", "")
    if not configured:
        return False
    return request.headers.get("x-admin-key", "") == configured


def _require_admin_key(request: Request) -> JSONResponse | None:
    if _admin_key_valid(request):
        return None
    status = 403 if (TRANSLATOR_ADMIN_KEY or os.environ.get("TRANSLATOR_ADMIN_KEY", "")) else 503
    return JSONResponse(
        {
            "error": {
                "message": "translator admin mutations are disabled or unauthorized",
                "code": "admin_key_required",
            }
        },
        status_code=status,
    )


def _admin_load_litellm_config() -> tuple[dict | None, list[dict]]:
    """Load litellm-config.yaml. Returns (config_or_None, errors)."""
    try:
        with open(LITELLM_CONFIG_PATH) as fh:
            return yaml.safe_load(fh) or {}, []
    except FileNotFoundError:
        return None, [
            _admin_error(
                "config_not_found",
                f"{LITELLM_CONFIG_PATH} not found",
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
    return ModelRegistryStore()


def _credential_inventory_store() -> CredentialInventoryStore:
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

    fallback = load_models_from_litellm_config(LITELLM_CONFIG_PATH)
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
    if _client is None:
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
        resp = await _client.post(
            f"{LITELLM}/v1/chat/completions",
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
    translator_provider_requests_total and translator_provider_rate_limits_total series.
    """
    signals: list[dict] = []
    if not text:
        return signals
    line_re = re.compile(
        r"^(translator_provider_requests_total|translator_provider_rate_limits_total)\{([^}]*)\}\s+([0-9.eE+]+)"
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
        "translator_base_url": os.environ.get("TRANSLATOR_BASE_URL", "http://localhost:4000"),
        "litellm_ui_url": os.environ.get("LITELLM_UI_URL", "http://localhost:4001"),
        "cliproxy_management_url": os.environ.get("CLIPROXY_MANAGEMENT_URL", "http://localhost:8317/management.html"),
        "cpa_manager_url": os.environ.get("CPA_MANAGER_URL", "http://localhost:18317/management.html"),
    }


def _admin_health_panel() -> dict:
    # Translator is serving by definition; other services are linked but not
    # actively probed in v1 (avoids unbounded calls). They are marked unknown.
    env = _admin_environment()
    services = [
        {"name": "translator", "status": "ok", "endpoint": env["translator_base_url"]},
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
    return _admin_panel("ok", "translator:self", 0, [], {"services": services})


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
    visible_aliases = {v[len(MODEL_PREFIX) :] if v.startswith(MODEL_PREFIX) else v for v in visible}
    models = []
    drift = []
    registry_by_id = {model.model_id: model for model in registry_models}
    for alias in sorted(set(configured)):
        is_visible = alias in visible_aliases
        registry_record = registry_by_id.get(alias)
        models.append(
            {
                "id": f"{MODEL_PREFIX}{alias}",
                "config_alias": alias,
                "provider_family": registry_record.family if registry_record else _provider_of(alias),
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
                "id": f"{MODEL_PREFIX}{alias}",
                "config_alias": alias,
                "provider_family": _provider_of(alias),
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
        (registry.source if registry is not None else "translator:/v1/models + repo:litellm-config.yaml"),
        0,
        panel_errors,
        {
            "visible_count": len(visible),
            "configured_count": len(configured),
            "registry_available": registry.registry_available if registry is not None else False,
            "prefix": MODEL_PREFIX,
            "models": models,
            "drift": drift,
        },
    )


def _admin_policy_trace_enabled() -> bool:
    return ADMIN_POLICY_TRACE_ENABLED


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
    _policy_trace.evaluate_ms = round(evaluate_ms, 2)
    _policy_trace.evaluated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _policy_trace.decision = decision
    _policy_trace.error = error
    if isinstance(decision, dict) and decision.get("policy_version"):
        _policy_version_hint = str(decision["policy_version"])


def _redact_policy_decision_for_admin(decision: dict) -> dict:
    """Bounded, redacted RoutingDecision sample for operator console."""
    sample: dict = {}
    for key in ("gate", "rules_applied", "policy_version", "quota_aware_mode"):
        if key in decision:
            sample[key] = decision[key]
    if decision.get("quota_aware_mode"):
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
        "enabled": POLICY_ENGINE_ENABLED,
        "trace_enabled": True,
        "policy_version": policy_version or _policy_version_hint,
        "redis_connected": redis_connected,
        "last_evaluate_ms": _policy_trace.evaluate_ms,
    }
    if _policy_trace.decision:
        data["last_decision"] = _redact_policy_decision_for_admin(_policy_trace.decision)
    if _policy_trace.error:
        data["last_error"] = _admin_redact(_policy_trace.error)[0]
    return data


async def _admin_policy_engine_connectivity() -> tuple[bool | None, str | None]:
    """Best-effort Redis ping and policy-engine health for admin trace."""
    redis_connected: bool | None = None
    if _redis is not None:
        try:
            await _redis.ping()
            redis_connected = True
        except Exception:
            redis_connected = False
    policy_version = _policy_version_hint
    if _client is not None:
        try:
            resp = await _client.get(f"{POLICY_ENGINE_URL}/v1/health", timeout=1.0)
            if resp.status_code == 200:
                body = resp.json()
                if isinstance(body, dict) and body.get("policy_version"):
                    policy_version = str(body["policy_version"])
        except Exception:
            pass
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
        "websocket_policy_bypass": codex_ws_policy_bypass(),
        "websocket_policy_evaluate_enabled": _policy_engine_ws_evaluate_enabled(),
        "policy_engine_enabled": _policy_engine_enabled(),
    }
    if policy_engine is not None:
        data["policy_engine"] = policy_engine
    return _admin_panel(
        status,
        "repo:litellm-config.yaml + translator:/metrics",
        15,
        errors,
        data,
    )


def _admin_providers_panel() -> dict:
    # Best-effort enrichment from the read-only health command. Parsed minimally;
    # any failure degrades the panel rather than failing the endpoint.
    script = os.environ.get("CLIPROXY_SETUP_PATH", "./cliproxy-setup.sh")
    stdout, errors = _admin_run_readonly_command([script, "health"], timeout=3.0)
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
        with open(LITELLM_CONFIG_PATH) as fh:
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
            # Match token counters: translator_token_input_total{provider="...",model="..."} value
            m = re.match(
                r'translator_token_(input|output)_total\{provider="([^"]+)",model="([^"]+)"\}\s+([\d.e+]+)',
                line,
            )
            if not m:
                canonical_match = re.match(
                    r"translator_token_canonical_(input|output)_total\{([^}]*)\}\s+([\d.e+]+)",
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
        "translator:/metrics (token counters)",
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
    if _client is None:
        return None, [
            _admin_error(
                "client_unavailable",
                "http client not initialized",
                "translator:/v1/models",
            )
        ]
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    headers = {"authorization": f"Bearer {master_key}"} if master_key else {}
    try:
        resp = await _client.get(f"{LITELLM}/v1/models", headers=headers, timeout=2.0)
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
        return None, [_admin_error("metrics_error", f"{type(exc).__name__}: {exc}", "translator:/metrics")]


async def _fetch_cliproxy_auth_files() -> tuple[list[dict], list[dict]]:
    if _client is None:
        return [], [
            _admin_error(
                "client_unavailable",
                "http client not initialized",
                "cliproxy:/v0/management/auth-files",
            )
        ]
    management_key = CLIPROXY_MANAGEMENT_KEY or os.environ.get("CLIPROXY_MANAGEMENT_KEY", "")
    if not management_key:
        return [], [
            _admin_error(
                "management_key_missing",
                "CLIPROXY_MANAGEMENT_KEY is required",
                "cliproxy:/v0/management/auth-files",
            )
        ]
    try:
        resp = await _client.get(
            f"{CLIPROXY_URL}/v0/management/auth-files",
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


async def _fetch_cliproxy_models_for_registry() -> tuple[list[dict], list[dict]]:
    if _client is None:
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
        resp = await _client.get(
            f"{CLIPROXY_URL}/v1/models",
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
    return await process_credential_event_async(event)


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
                        await _emit_credential_transition_to_policy(transition)
                    except Exception as exc:
                        errors.append(
                            _admin_error(
                                "policy_event_error",
                                f"{type(exc).__name__}: {exc}",
                                "translator:policy-event",
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
        CredentialInventorySyncRequest(dry_run=TRANSLATOR_CREDENTIAL_SYNC_DRY_RUN)
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
    if TRANSLATOR_CREDENTIAL_SYNC_INITIAL_DELAY_SEC:
        await asyncio.sleep(TRANSLATOR_CREDENTIAL_SYNC_INITIAL_DELAY_SEC)
    while True:
        try:
            await _run_scheduled_credential_sync()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("credential sync scheduler failed: %s: %s", type(exc).__name__, _admin_redact(str(exc))[0])
        await asyncio.sleep(TRANSLATOR_CREDENTIAL_SYNC_INTERVAL_SEC)


@app.get("/admin/analytics/tokens")
async def admin_token_analytics():
    """Granular token usage analytics by provider and model (#117)."""
    metrics_text, errors = await _admin_fetch_metrics_text()
    return _admin_token_analytics_panel(metrics_text, errors)


@app.get("/admin/credentials", response_model=CredentialInventoryListResponse)
async def admin_credentials():
    """List redacted translator credential inventory records."""
    loaded = _credential_inventory_store().list_credentials()
    return loaded.model_copy(update={"credentials": _redact_credential_records(loaded.credentials)})


@app.post("/admin/credentials/sync", response_model=CredentialInventorySyncResponse)
async def admin_credentials_sync(request: Request, body: CredentialInventorySyncRequest):
    """Sync CLIProxy auth-file state into credential_inventory."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error
    return await _sync_credentials_from_cliproxy(body)


@app.post("/admin/credentials/{credential_id}/probe", response_model=CredentialProbeResponse)
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


@app.get("/admin/models", response_model=ModelRegistryListResponse)
async def admin_models():
    """List translator-owned model registry records, falling back to LiteLLM config."""
    return _load_model_registry_with_config_fallback()


@app.post("/admin/models", response_model=ModelRegistryMutationResponse)
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


@app.get("/admin/models/{model_id}", response_model=ModelRegistryListResponse)
async def admin_model(model_id: str):
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


@app.patch("/admin/models/{model_id}", response_model=ModelRegistryMutationResponse)
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


@app.delete("/admin/models/{model_id}", response_model=ModelRegistryMutationResponse)
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


@app.post("/admin/models/{model_id}/probe", response_model=ModelProbeResponse)
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


@app.post("/admin/models/reconcile", response_model=ModelRegistryReconcileResponse)
async def admin_models_reconcile(request: Request, body: ModelRegistryReconcileRequest):
    """Render registry-driven LiteLLM/Gemini config changes without writing files."""
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error

    loaded = _load_model_registry_with_config_fallback()
    litellm_text, litellm_errors = _read_text_file_for_reconcile(
        LITELLM_CONFIG_PATH,
        "repo:litellm-config.yaml",
    )
    gemini_text, gemini_errors = _read_text_file_for_reconcile(
        GEMINI_MODEL_MAP_PATH,
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


@app.post("/admin/models/sync", response_model=ModelRegistrySyncResponse)
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
        loaded = load_models_from_litellm_config(LITELLM_CONFIG_PATH)
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


@app.get("/admin/status")
async def admin_status():
    """Read-only operator status aggregator (admin-console.v1)."""
    config, config_errors = _admin_load_litellm_config()
    registry = _load_model_registry_with_config_fallback()
    visible_ids, model_errors = await _admin_fetch_visible_models()
    metrics_text, metrics_errors = await _admin_fetch_metrics_text()
    redis_ok, policy_version = await _admin_policy_engine_connectivity()
    policy_engine = _build_admin_policy_engine_data(
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


@app.get("/admin/dashboard")
async def admin_dashboard():
    """Read-only operator dashboard page; renders /admin/status client-side."""
    return HTMLResponse(content=_ADMIN_DASHBOARD_HTML)


# ── Catch-all proxy (Cursor / generic OpenAI-compatible clients) ─────────────


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    raw = await request.body()

    body, prefix_stripped = _strip_prefix(raw)
    body, fmt_changed = _patch_body(path, body if prefix_stripped else raw)
    if not fmt_changed and not prefix_stripped:
        body = raw
    changed = prefix_stripped or fmt_changed

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
