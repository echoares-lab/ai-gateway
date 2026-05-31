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
import re
from dataclasses import dataclass
import httpx
import websockets
import redis.asyncio as aioredis
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("translator")

UPSTREAM_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "30.0"))

@asynccontextmanager
async def _lifespan(application: FastAPI):
    global _client, _redis
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
    yield
    if _client is not None:
        await _client.aclose()
    if _redis is not None:
        await _redis.aclose()


app = FastAPI(lifespan=_lifespan)
LITELLM = os.environ.get("LITELLM_URL", "http://litellm:4000")
MODEL_PREFIX = "AI-Gateway:"

REQUEST_COUNT = Counter(
    "translator_requests_total",
    "Total translator HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "translator_request_duration_seconds",
    "Translator request latency in seconds",
    ["method", "path"],
)
UPSTREAM_ERRORS = Counter(
    "translator_upstream_errors_total",
    "Translator upstream errors by path and status",
    ["path", "status"],
)
CACHE_HITS = Counter(
    "translator_cache_hits_total",
    "Translator cache hits",
    ["path", "kind"],
)
CACHE_MISSES = Counter(
    "translator_cache_misses_total",
    "Translator cache misses",
    ["path", "kind"],
)
FORMAT_REQUESTS = Counter(
    "translator_format_requests_total",
    "Requests by translated API format",
    ["format"],
)
IN_FLIGHT = Counter(
    "translator_in_flight_total",
    "Total requests entering translator middleware",
)

@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)



_client: httpx.AsyncClient | None = None
# NOTE: Translator caching is DISABLED in favor of LiteLLM's auth-aware Redis cache.
# LiteLLM's cache includes Authorization header in its cache key, preventing cross-user responses.
# Translator caching layer is redundant when multi-team virtual keys are in use.
# Set CACHE_ENABLED=true only if LiteLLM's cache is unavailable or disabled.
CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "false").lower() not in ("0", "false", "no")
CACHE_TTL = int(os.environ.get("CACHE_TTL_SECONDS", "60"))
_redis: aioredis.Redis | None = None


def _cache_key(model: str, messages: list, tools: list | None = None) -> str | None:
    if not CACHE_ENABLED or _redis is None:
        return None
    key_data: dict = {"m": model, "msgs": messages}
    if tools:
        key_data["tools"] = tools
    digest = hashlib.sha256(
        json.dumps(key_data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
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
                    status_code=413
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


async def _post_with_retry(url: str, headers: dict, content: bytes, retries: int = 2) -> httpx.Response:
    """POST to LiteLLM with retry on transient 502/503."""
    for attempt in range(retries + 1):
        resp = await _client.post(url, headers=headers, content=content)
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
            return {"type": "image_url", "image_url": {"url": c["url"], "detail": detail}}
        if "source" in c:
            src = c["source"]
            if src.get("type") == "url":
                return {"type": "image_url", "image_url": {"url": src["url"], "detail": detail}}
            if src.get("type") == "base64":
                media = src.get("media_type", "image/jpeg")
                return {"type": "image_url", "image_url": {
                    "url": f"data:{media};base64,{src['data']}", "detail": detail
                }}
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
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": list(pending_calls),
            })
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
                    c for c in content
                    if isinstance(c, dict) and c.get("type") in ("tool_use", "function_call")
                ]
                if tool_blocks:
                    tool_calls = []
                    text_parts = []
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") in ("tool_use", "function_call"):
                            args = c.get("input", c.get("arguments", {}))
                            tool_calls.append({
                                "id": c.get("id", c.get("call_id", "")),
                                "type": "function",
                                "function": {
                                    "name": c.get("name", ""),
                                    "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                                },
                            })
                        elif c.get("type") in ("text", "input_text", "output_text"):
                            text_parts.append(c.get("text", ""))
                    messages.append({
                        "role": "assistant",
                        "content": "".join(text_parts) or None,
                        "tool_calls": tool_calls,
                    })
                    continue
            messages.append({"role": role, "content": _normalize_content(content)})

        elif t == "function_call":
            args = item.get("arguments", "{}")
            pending_calls.append({
                "id": item.get("id", item.get("call_id", "")),
                "type": "function",
                "function": {
                    "name": item.get("name", ""),
                    "arguments": args if isinstance(args, str) else json.dumps(args),
                },
            })

        elif t == "function_call_output":
            flush_calls()
            messages.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", item.get("id", "")),
                "content": str(item.get("output", "")),
            })

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
            out.append({
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {}),
                },
            })
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


def _resolve_model(model: str, endpoint: str, wants_tools: bool = False, gemini_map: dict | None = None) -> _ResolvedModel:
    requested = model or ""
    effective = requested
    reason = "passthrough"
    severity = "info"
    assumption = "native"

    if effective.startswith(MODEL_PREFIX):
        effective = effective[len(MODEL_PREFIX):]
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
        if ("preview" in effective or "exp" in effective) and endpoint in ("responses", "chat", "claude"):
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
        data["model"] = model[len(MODEL_PREFIX):]
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
            log.info("Input item types: %s", [i.get("type") if isinstance(i, dict) else type(i).__name__ for i in inp])
        data["messages"] = _responses_input_to_messages(inp)
        n = len(inp) if isinstance(inp, list) else 1
        log.info("Translated Responses API input (%d items) → %d messages", n, len(data["messages"]))
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


# ── Gemini format converters ─────────────────────────────────────────────────

# Legacy Google model names that need redirecting to current equivalents.
# Managed by hand — these don't change once a generation is deprecated.
_GEMINI_LEGACY_MAP = {
    "gemini-pro":                     "gemini-3-1-pro-preview",
    "gemini-1.0-pro":                 "gemini-3-1-pro-preview",
    "gemini-1.5-pro":                 "gemini-3-1-pro-preview",
    "gemini-1.5-pro-latest":          "gemini-3-1-pro-preview",
    "gemini-1.5-flash":               "gemini-3-flash-preview",
    "gemini-1.5-flash-latest":        "gemini-3-flash-preview",
    "gemini-2.0-flash":               "gemini-3-flash-preview",
    "gemini-2.0-flash-exp":           "gemini-3-flash-preview",
}

# Current dotted→dashed mappings are kept in gemini-model-map.json and managed
# by sync-models. This module watches the file and reloads on change.
_GEMINI_MAP_PATH = "/app/gemini-model-map.json"
_gemini_map_mtime: float = 0.0
_gemini_map_dynamic: dict = {}


def _get_gemini_map() -> dict:
    global _gemini_map_mtime, _gemini_map_dynamic
    try:
        mtime = os.stat(_GEMINI_MAP_PATH).st_mtime
        if mtime != _gemini_map_mtime:
            with open(_GEMINI_MAP_PATH) as f:
                _gemini_map_dynamic = json.load(f)
            _gemini_map_mtime = mtime
            log.info("Reloaded gemini-model-map.json (%d entries)", len(_gemini_map_dynamic))
    except Exception:
        pass
    return {**_GEMINI_LEGACY_MAP, **_gemini_map_dynamic}

GEMINI_FINISH_MAP = {
    "stop": "STOP",
    "length": "MAX_TOKENS",
    "tool_calls": "STOP",
    "content_filter": "SAFETY",
}


def _find_tool_call_id_in_history(history: list, target_name: str, current_index: int) -> str:
    """Scan backward from current_index in conversation history to find the most recent
    matching tool call by name and return a deterministic, valid alphanumeric ID.
    Supports both Gemini 'contents' format and standard OpenAI 'messages' format."""
    for i in range(current_index - 1, -1, -1):
        msg = history[i]
        if not isinstance(msg, dict):
            continue

        # 1. Check standard OpenAI format (messages)
        tool_calls = msg.get("tool_calls", [])
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    if isinstance(fn, dict) and fn.get("name") == target_name:
                        tc_id = tc.get("id")
                        if tc_id:
                            return tc_id
                        h = hashlib.md5(f"{target_name}_{i}".encode()).hexdigest()[:20]
                        return f"call_{h}"

        # 2. Check Gemini format (contents)
        parts = msg.get("parts", [])
        if isinstance(parts, list):
            for p in parts:
                if isinstance(p, dict) and "functionCall" in p:
                    fc = p["functionCall"]
                    if isinstance(fc, dict) and fc.get("name") == target_name:
                        h = hashlib.md5(f"{target_name}_{i}".encode()).hexdigest()[:20]
                        return f"call_{h}"

    # Fallback if not found in history
    h = hashlib.md5(f"{target_name}_fallback".encode()).hexdigest()[:20]
    return f"call_{h}"


def _gemini_req_to_oai(model: str, body: dict) -> dict:
    messages = []

    sys_inst = body.get("systemInstruction", {})
    if isinstance(sys_inst, dict):
        sys_text = "".join(p.get("text", "") for p in sys_inst.get("parts", []))
        if sys_text:
            messages.append({"role": "system", "content": sys_text})

    contents = body.get("contents", [])
    for content_idx, content in enumerate(contents):
        role = "assistant" if content.get("role") == "model" else content.get("role", "user")
        parts = content.get("parts", [])

        func_calls = [p["functionCall"] for p in parts if "functionCall" in p]
        func_resps = [p["functionResponse"] for p in parts if "functionResponse" in p]
        texts = [p.get("text", "") for p in parts if "text" in p]
        inline = [p for p in parts if "inlineData" in p or "fileData" in p]

        if func_resps:
            for fr in func_resps:
                tc_id = _find_tool_call_id_in_history(contents, fr["name"], content_idx)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": json.dumps(fr.get("response", {})),
                })
        elif func_calls:
            tool_calls = []
            for fc in func_calls:
                h = hashlib.md5(f"{fc['name']}_{content_idx}".encode()).hexdigest()[:20]
                tc_id = f"call_{h}"
                tool_calls.append({
                    "id": tc_id,
                    "type": "function",
                    "function": {
                        "name": fc["name"],
                        "arguments": json.dumps(fc.get("args", {})),
                    },
                })
            messages.append({
                "role": "assistant",
                "content": "".join(texts) or None,
                "tool_calls": tool_calls,
            })
        elif inline:
            content_list = []
            for p in parts:
                if "text" in p:
                    content_list.append({"type": "text", "text": p["text"]})
                elif "inlineData" in p:
                    d = p["inlineData"]
                    content_list.append({"type": "image_url", "image_url": {
                        "url": f"data:{d['mimeType']};base64,{d['data']}"
                    }})
            messages.append({"role": role, "content": content_list})
        else:
            messages.append({"role": role, "content": "".join(texts)})

    # Google exposes variants like gemini-3.1-pro-preview-customtools for tool-aware routing;
    # our CLIProxy backend handles tools with the base model so we strip known suffixes.
    resolved = _resolve_model(model, endpoint="gemini", wants_tools=bool(body.get("tools")), gemini_map=_get_gemini_map())
    oai = {"model": resolved.effective_model, "messages": messages}

    gc = body.get("generationConfig", {})
    if "maxOutputTokens" in gc:
        oai["max_tokens"] = gc["maxOutputTokens"]
    if "temperature" in gc:
        oai["temperature"] = gc["temperature"]
    if "topP" in gc:
        oai["top_p"] = gc["topP"]
    if "stopSequences" in gc:
        oai["stop"] = gc["stopSequences"]

    tools_out = []
    for tool_obj in body.get("tools", []):
        for fd in tool_obj.get("functionDeclarations", []):
            tools_out.append({
                "type": "function",
                "function": {
                    "name": fd["name"],
                    "description": fd.get("description", ""),
                    "parameters": fd.get("parameters", {"type": "object", "properties": {}}),
                },
            })
    if tools_out:
        oai["tools"] = tools_out

    mode = body.get("toolConfig", {}).get("functionCallingConfig", {}).get("mode", "")
    if mode == "ANY":
        oai["tool_choice"] = "required"
    elif mode == "NONE":
        oai["tool_choice"] = "none"

    return oai


def _oai_to_gemini_resp(oai: dict, model: str) -> dict:
    choice = oai.get("choices", [{}])[0]
    msg = choice.get("message", {})
    finish = choice.get("finish_reason", "stop")

    parts = []
    if msg.get("content"):
        parts.append({"text": msg["content"]})
    for tc in msg.get("tool_calls", []):
        fn = tc["function"]
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except Exception:
            args = {}
        parts.append({"functionCall": {"name": fn["name"], "args": args}})

    usage = oai.get("usage", {})
    return {
        "candidates": [{
            "content": {"role": "model", "parts": parts},
            "finishReason": GEMINI_FINISH_MAP.get(finish, "STOP"),
            "index": 0,
        }],
        "usageMetadata": {
            "promptTokenCount": usage.get("prompt_tokens", 0),
            "candidatesTokenCount": usage.get("completion_tokens", 0),
            "totalTokenCount": usage.get("total_tokens", 0),
        },
        "modelVersion": model,
    }


async def _gemini_stream(oai_lines):
    """Convert OpenAI SSE lines to Gemini SSE chunks."""
    tool_buffers: dict[int, dict] = {}

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
            finish = choice.get("finish_reason")

            parts = []
            if delta.get("content"):
                parts.append({"text": delta["content"]})

            for tc in delta.get("tool_calls", []):
                idx = tc.get("index", 0)
                fn = tc.get("function", {})
                if idx not in tool_buffers:
                    tool_buffers[idx] = {"name": fn.get("name", ""), "args": ""}
                if fn.get("name"):
                    tool_buffers[idx]["name"] = fn["name"]
                if fn.get("arguments"):
                    tool_buffers[idx]["args"] += fn["arguments"]

            # Flush completed tool calls on the finish chunk
            if finish:
                for tb in tool_buffers.values():
                    if tb["name"]:
                        try:
                            args = json.loads(tb["args"] or "{}")
                        except Exception:
                            args = {}
                        parts.append({"functionCall": {"name": tb["name"], "args": args}})

            if parts or finish:
                gemini_chunk = {
                    "candidates": [{
                        "content": {"role": "model", "parts": parts},
                        "finishReason": GEMINI_FINISH_MAP.get(finish, "") if finish else None,
                        "index": 0,
                    }]
                }
                yield f"data: {json.dumps(gemini_chunk)}\n\n"
    except httpx.HTTPError as exc:
        log.error("Gemini stream connection error: %s", exc)


@app.api_route("/v1beta/models/{model_action:path}", methods=["GET", "POST"])
async def gemini_proxy(model_action: str, request: Request):
    if request.method == "GET":
        # Pass through to LiteLLM (e.g. model info requests)
        resp = await _client.get(f"{LITELLM}/v1beta/models/{model_action}",
                                 params=dict(request.query_params), timeout=30)
        return Response(content=resp.content, status_code=resp.status_code,
                        headers={"content-type": "application/json"})

    if ":" not in model_action:
        return Response(content=json.dumps({"error": {"message": "Invalid path", "code": 400}}),
                        status_code=400, headers={"content-type": "application/json"})

    model, action = model_action.rsplit(":", 1)
    streaming = action == "streamGenerateContent"

    raw = await request.body()
    try:
        body = json.loads(raw)
    except Exception:
        body = {}

    params = dict(request.query_params)
    api_key = (params.pop("key", None)
               or request.headers.get("x-goog-api-key")
               or request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None)
    auth = f"Bearer {api_key}" if api_key else ""

    oai_body = _gemini_req_to_oai(model, body)
    if streaming:
        oai_body["stream"] = True

    oai_bytes = json.dumps(oai_body).encode()
    headers = {
        "content-type": "application/json",
        "authorization": auth,
        "content-length": str(len(oai_bytes)),
    }

    ck = _cache_key(oai_body.get("model", ""), oai_body.get("messages", []),
                    oai_body.get("tools"))
    log.info("Gemini %s → model=%s tools=%d stream=%s",
             action, oai_body["model"], len(oai_body.get("tools", [])), streaming)

    if streaming:
        async def generate():
            if ck:
                cached = await _cache_get(ck)
                if cached is not None:
                    log.info("cache hit (gemini stream) key=%s", ck[:16])
                    async for chunk in _gemini_stream(_aiter_list(cached)):
                        yield chunk
                    return
            buf: list[str] = []
            try:
                async with _client.stream("POST", f"{LITELLM}/v1/chat/completions",
                                          headers=headers, content=oai_bytes) as resp:
                    async for chunk in _gemini_stream(_tee_lines(resp.aiter_lines(), buf)):
                        yield chunk
            except Exception as exc:
                log.error("Gemini stream upstream error model=%s: %s: %s",
                          oai_body.get("model"), type(exc).__name__, exc)
                return
            if ck and buf:
                await _cache_set(ck, buf)
        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (gemini) key=%s", ck[:16])
            try:
                return Response(content=json.dumps(
                    _oai_to_gemini_resp(json.loads(cached_json[0]), model)
                ).encode(), status_code=200, headers={"content-type": "application/json"})
            except Exception:
                pass

    resp = await _post_with_retry(f"{LITELLM}/v1/chat/completions", headers, oai_bytes)

    if resp.status_code >= 400:
        log.warning("Gemini upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(content=resp.content, status_code=resp.status_code,
                        headers={"content-type": "application/json"})

    try:
        resp_json = resp.json()
        if ck:
            await _cache_set(ck + ":json", [json.dumps(resp_json)])
        gemini_resp = _oai_to_gemini_resp(resp_json, model)
        return Response(content=json.dumps(gemini_resp).encode(), status_code=200,
                        headers={"content-type": "application/json"})
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
        output.append({
            "type": "function_call",
            "id": tc.get("id", ""),
            "call_id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "arguments": fn.get("arguments", "{}"),
            "status": "completed",
        })

    content = msg.get("content") or ""
    if content or not output:
        output.append({
            "type": "message",
            "id": f"msg_{oai_id}",
            "role": "assistant",
            "content": [{"type": "output_text", "text": content, "annotations": []}],
            "status": "completed",
        })

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

    yield _sse("response.created", {
        "type": "response.created",
        "response": {"id": resp_id, "object": "response", "status": "in_progress", "output": []},
    })
    yield _sse("response.in_progress", {
        "type": "response.in_progress",
        "response": {"id": resp_id, "object": "response", "status": "in_progress"},
    })

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
                    yield _sse("response.output_item.added", {
                        "type": "response.output_item.added",
                        "output_index": 0,
                        "item": {"type": "message", "id": msg_id, "role": "assistant",
                                 "content": [], "status": "in_progress"},
                    })
                    yield _sse("response.content_part.added", {
                        "type": "response.content_part.added",
                        "item_id": msg_id, "output_index": 0, "content_index": 0,
                        "part": {"type": "output_text", "text": "", "annotations": []},
                    })
                text_buffer += text
                yield _sse("response.output_text.delta", {
                    "type": "response.output_text.delta",
                    "item_id": msg_id, "output_index": 0, "content_index": 0,
                    "delta": text,
                })

            for tc_delta in delta.get("tool_calls", []):
                idx = tc_delta.get("index", 0)
                fn = tc_delta.get("function", {})
                if idx not in tool_buffers:
                    tc_id = tc_delta.get("id", f"call_{uuid.uuid4().hex[:24]}")
                    tc_name = fn.get("name", "")
                    tool_buffers[idx] = {"id": tc_id, "name": tc_name, "args": ""}
                    yield _sse("response.output_item.added", {
                        "type": "response.output_item.added",
                        "output_index": idx,
                        "item": {"type": "function_call", "id": tc_id, "call_id": tc_id,
                                 "name": tc_name, "arguments": "", "status": "in_progress"},
                    })
                if fn.get("name") and not tool_buffers[idx]["name"]:
                    tool_buffers[idx]["name"] = fn["name"]
                if fn.get("arguments"):
                    tool_buffers[idx]["args"] += fn["arguments"]
                    yield _sse("response.function_call_arguments.delta", {
                        "type": "response.function_call_arguments.delta",
                        "item_id": tool_buffers[idx]["id"],
                        "output_index": idx,
                        "delta": fn["arguments"],
                    })
    except httpx.HTTPError as exc:
        log.error("Responses stream connection error: %s", exc)

    # Close text
    if text_started:
        yield _sse("response.output_text.done", {
            "type": "response.output_text.done",
            "item_id": msg_id, "output_index": 0, "content_index": 0, "text": text_buffer,
        })
        yield _sse("response.content_part.done", {
            "type": "response.content_part.done",
            "item_id": msg_id, "output_index": 0, "content_index": 0,
            "part": {"type": "output_text", "text": text_buffer, "annotations": []},
        })
        yield _sse("response.output_item.done", {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {"type": "message", "id": msg_id, "role": "assistant",
                     "content": [{"type": "output_text", "text": text_buffer, "annotations": []}],
                     "status": "completed"},
        })

    # Close tool calls
    for idx, tc in sorted(tool_buffers.items()):
        yield _sse("response.function_call_arguments.done", {
            "type": "response.function_call_arguments.done",
            "item_id": tc["id"], "output_index": idx, "arguments": tc["args"],
        })
        yield _sse("response.output_item.done", {
            "type": "response.output_item.done",
            "output_index": idx,
            "item": {"type": "function_call", "id": tc["id"], "call_id": tc["id"],
                     "name": tc["name"], "arguments": tc["args"], "status": "completed"},
        })

    yield _sse("response.completed", {
        "type": "response.completed",
        "response": {"id": resp_id, "object": "response", "status": "completed"},
    })


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

    expected_master_key = os.environ.get("LITELLM_MASTER_KEY", "sk-a3698c2000395d1181397b256415e680")
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
        log.warning("Unauthorized Codex WebSocket connection attempt with token: %s", client_auth)
        try:
            await ws.close(code=1008, reason="Unauthorized")
        except Exception:
            pass
        return

    # Target CLIProxy WebSocket URL
    cliproxy_ws_url = os.environ.get("CLIPROXY_WS_URL", "ws://cliproxy:8317/v1/responses")

    # Filter client handshake headers to forward to CLIProxy
    headers = {}
    for k, v in ws.headers.items():
        k_lower = k.lower()
        if k_lower not in (
            "host",
            "upgrade",
            "connection",
            "sec-websocket-key",
            "sec-websocket-version",
            "sec-websocket-extensions",
            "sec-websocket-protocol",
            "content-length"
        ):
            headers[k] = v

    # Translate master key to CLIProxy API Key for the upstream connection
    cliproxy_api_key = os.environ.get("CLIPROXY_API_KEY", "cliproxy-Wtgxs0tEBb4Usyam5qYg")
    if cliproxy_api_key:
        headers["authorization"] = f"Bearer {cliproxy_api_key}"

    log.info("Proxying Codex WebSocket to upstream: %s", cliproxy_ws_url)
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
                                    "type": "timeout_error"
                                }
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
        log.error("Failed to connect or proxy Codex WebSocket to upstream %s: %s", cliproxy_ws_url, exc)
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
        return Response(content=json.dumps({"error": "Invalid JSON"}), status_code=400,
                        headers={"content-type": "application/json"})

    streaming = body.get("stream", False)
    oai_body = _responses_req_to_oai(body)
    if streaming:
        oai_body["stream"] = True

    oai_bytes = json.dumps(oai_body).encode()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "content-type")
    }
    if "authorization" not in {k.lower() for k in headers}:
        master_key = os.environ.get("LITELLM_MASTER_KEY", "sk-a3698c2000395d1181397b256415e680")
        headers["authorization"] = f"Bearer {master_key}"
    headers["content-type"] = "application/json"
    headers["content-length"] = str(len(oai_bytes))

    ck = _cache_key(oai_body.get("model", ""), oai_body.get("messages", []),
                    oai_body.get("tools"))
    log.info("Codex request headers: %s", {k: v for k, v in request.headers.items()})
    log.info("Codex Responses API → model=%s tools=%d stream=%s",
             oai_body.get("model"), len(oai_body.get("tools", [])), streaming)

    if streaming:
        async def generate():
            if ck:
                cached = await _cache_get(ck)
                if cached is not None:
                    log.info("cache hit (responses stream) key=%s", ck[:16])
                    async for event in _oai_to_responses_stream(_aiter_list(cached)):
                        yield event
                    return
            buf: list[str] = []
            try:
                async with _client.stream("POST", f"{LITELLM}/v1/chat/completions",
                                          headers=headers, content=oai_bytes) as resp:
                    async for event in _oai_to_responses_stream(_tee_lines(resp.aiter_lines(), buf)):
                        yield event
            except httpx.TimeoutException as exc:
                log.error("Responses stream upstream timed out: %s", exc)
                err_id = f"resp_{uuid.uuid4().hex[:24]}"
                err_msg = f"Upstream request timed out after {UPSTREAM_TIMEOUT} seconds. Please check LiteLLM readiness."
                yield _sse("error", {"type": "error", "error": {"message": err_msg, "type": "timeout_error"}})
                yield _sse("response.completed", {"type": "response.completed", "response": {
                    "id": err_id, "object": "response", "status": "failed"}})
                return
            except Exception as exc:
                log.error("Responses stream upstream error model=%s: %s: %s",
                          oai_body.get("model"), type(exc).__name__, exc)
                err_id = f"resp_{uuid.uuid4().hex[:24]}"
                err_msg = f"Upstream connection failed: {exc}"
                yield _sse("error", {"type": "error", "error": {"message": err_msg, "type": "connection_error"}})
                yield _sse("response.completed", {"type": "response.completed", "response": {
                    "id": err_id, "object": "response", "status": "failed"}})
                return
            if ck and buf:
                await _cache_set(ck, buf)
        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (responses) key=%s", ck[:16])
            try:
                return Response(content=json.dumps(
                    _oai_to_responses_resp(json.loads(cached_json[0]))
                ).encode(), status_code=200, headers={"content-type": "application/json"})
            except Exception:
                pass

    try:
        resp = await _post_with_retry(f"{LITELLM}/v1/chat/completions", headers, oai_bytes)
    except httpx.TimeoutException as exc:
        log.error("Codex upstream request timed out: %s", exc)
        err_msg = f"Upstream request timed out after {UPSTREAM_TIMEOUT} seconds. Please check LiteLLM readiness."
        return Response(content=json.dumps({"error": {"message": err_msg, "type": "timeout_error"}}).encode(),
                        status_code=504, headers={"content-type": "application/json"})
    except Exception as exc:
        log.error("Codex upstream request failed: %s", exc)
        err_msg = f"Upstream connection failed: {exc}"
        return Response(content=json.dumps({"error": {"message": err_msg, "type": "connection_error"}}).encode(),
                        status_code=502, headers={"content-type": "application/json"})

    if resp.status_code >= 400:
        log.warning("Codex upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(content=resp.content, status_code=resp.status_code,
                        headers={"content-type": "application/json"})

    try:
        resp_json = resp.json()
        if ck:
            await _cache_set(ck + ":json", [json.dumps(resp_json)])
        responses_resp = _oai_to_responses_resp(resp_json)
        return Response(content=json.dumps(responses_resp).encode(), status_code=200,
                        headers={"content-type": "application/json"})
    except Exception as e:
        log.error("Codex response conversion error: %s", e)
        return Response(content=resp.content, status_code=resp.status_code)


# ── Claude / Anthropic Messages API converters ───────────────────────────────

def _claude_msg_to_oai(msg: dict) -> list[dict]:
    role = msg.get("role", "user")
    content = msg.get("content", "")

    if isinstance(content, str):
        return [{"role": role, "content": content}]
    if not isinstance(content, list):
        return [{"role": role, "content": str(content)}]

    tool_uses = [c for c in content if c.get("type") == "tool_use"]
    tool_results = [c for c in content if c.get("type") == "tool_result"]
    text_blocks = [c for c in content if c.get("type") == "text"]
    image_blocks = [c for c in content if c.get("type") == "image"]

    if tool_results:
        out = []
        for tr in tool_results:
            tr_content = tr.get("content", "")
            if isinstance(tr_content, list):
                tr_content = " ".join(b.get("text", "") for b in tr_content if b.get("type") == "text")
            out.append({
                "role": "tool",
                "tool_call_id": tr.get("tool_use_id", ""),
                "content": str(tr_content),
            })
        return out

    if tool_uses:
        text = "".join(b.get("text", "") for b in text_blocks)
        tool_calls = []
        for tu in tool_uses:
            inp = tu.get("input", {})
            tool_calls.append({
                "id": tu.get("id", ""),
                "type": "function",
                "function": {
                    "name": tu.get("name", ""),
                    "arguments": json.dumps(inp) if isinstance(inp, dict) else str(inp),
                },
            })
        return [{"role": "assistant", "content": text or None, "tool_calls": tool_calls}]

    if image_blocks:
        content_list = []
        for block in content:
            if block.get("type") == "text":
                content_list.append({"type": "text", "text": block.get("text", "")})
            elif block.get("type") == "image":
                src = block.get("source", {})
                if src.get("type") == "base64":
                    url = f"data:{src.get('media_type', 'image/jpeg')};base64,{src.get('data', '')}"
                    content_list.append({"type": "image_url", "image_url": {"url": url}})
                elif src.get("type") == "url":
                    content_list.append({"type": "image_url", "image_url": {"url": src.get("url", "")}})
        return [{"role": role, "content": content_list}]

    return [{"role": role, "content": "".join(b.get("text", "") for b in text_blocks)}]


def _claude_req_to_oai(body: dict) -> dict:
    resolved = _resolve_model(body.get("model", ""), endpoint="claude", wants_tools=bool(body.get("tools")))
    model = resolved.effective_model
    if "[" in model and model.endswith("]"):
        model = model.split("[")[0]

    messages = []

    system = body.get("system", "")
    if isinstance(system, list):
        system = "".join(b.get("text", "") for b in system if b.get("type") == "text")
    if system:
        messages.append({"role": "system", "content": system})

    for msg in body.get("messages", []):
        messages.extend(_claude_msg_to_oai(msg))

    oai: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": body.get("max_tokens", 4096),
    }

    if "temperature" in body:
        oai["temperature"] = body["temperature"]
    if "top_p" in body:
        oai["top_p"] = body["top_p"]
    if "stop_sequences" in body:
        oai["stop"] = body["stop_sequences"]

    tools = body.get("tools", [])
    if tools:
        oai["tools"] = []
        for t in tools:
            oai["tools"].append({
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            })

    tc = body.get("tool_choice", {})
    if isinstance(tc, dict) and tc:
        tc_type = tc.get("type", "")
        if tc_type == "auto":
            oai["tool_choice"] = "auto"
        elif tc_type == "any":
            oai["tool_choice"] = "required"
        elif tc_type == "tool":
            oai["tool_choice"] = {"type": "function", "function": {"name": tc.get("name", "")}}

    return oai


def _oai_to_claude_resp(oai: dict) -> dict:
    choice = oai.get("choices", [{}])[0]
    msg = choice.get("message", {})
    finish = choice.get("finish_reason", "stop")
    usage = oai.get("usage", {})

    content = []
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})

    stop_reason = "end_turn"
    for tc in msg.get("tool_calls", []):
        fn = tc["function"]
        stop_reason = "tool_use"
        try:
            inp = json.loads(fn.get("arguments", "{}"))
        except Exception:
            inp = {}
        content.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": fn.get("name", ""),
            "input": inp,
        })

    if finish == "length":
        stop_reason = "max_tokens"

    return {
        "id": f"msg_{oai.get('id', uuid.uuid4().hex)}",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": oai.get("model", ""),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


async def _oai_to_claude_stream(oai_lines, model: str):
    """Convert OpenAI SSE lines to Anthropic SSE events."""
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 1}}})}\n\n"
    yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"

    text_block_index: int | None = None
    text_buffer = ""
    tool_blocks: dict[int, dict] = {}  # oai index → {id, name, args, block_index}
    next_block = 0
    finish_reason = "end_turn"
    output_tokens = 0

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
            finish = choice.get("finish_reason")
            usage = chunk.get("usage", {})

            if usage.get("completion_tokens"):
                output_tokens = usage["completion_tokens"]
            if finish:
                if finish == "tool_calls":
                    finish_reason = "tool_use"
                elif finish == "length":
                    finish_reason = "max_tokens"

            text = delta.get("content", "")
            if text:
                if text_block_index is None:
                    text_block_index = next_block
                    next_block += 1
                    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': text_block_index, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                text_buffer += text
                yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': text_block_index, 'delta': {'type': 'text_delta', 'text': text}})}\n\n"

            for tc_delta in delta.get("tool_calls", []):
                idx = tc_delta.get("index", 0)
                fn = tc_delta.get("function", {})
                if idx not in tool_blocks:
                    tc_id = tc_delta.get("id", f"toolu_{uuid.uuid4().hex[:24]}")
                    tc_name = fn.get("name", "")
                    bi = next_block
                    next_block += 1
                    tool_blocks[idx] = {"id": tc_id, "name": tc_name, "args": "", "block_index": bi}
                    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': bi, 'content_block': {'type': 'tool_use', 'id': tc_id, 'name': tc_name, 'input': {}}})}\n\n"
                if fn.get("name") and not tool_blocks[idx]["name"]:
                    tool_blocks[idx]["name"] = fn["name"]
                if fn.get("arguments"):
                    tool_blocks[idx]["args"] += fn["arguments"]
                    bi = tool_blocks[idx]["block_index"]
                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': bi, 'delta': {'type': 'input_json_delta', 'partial_json': fn['arguments']}})}\n\n"
    except httpx.HTTPError as exc:
        log.error("Claude stream connection error: %s", exc)

    if text_block_index is not None:
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"

    for idx, tb in sorted(tool_blocks.items()):
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': tb['block_index']})}\n\n"

    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': finish_reason, 'stop_sequence': None}, 'usage': {'output_tokens': output_tokens}})}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"


@app.post("/v1/messages")
async def claude_proxy(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw)
    except Exception:
        return Response(content=json.dumps({"error": {"type": "invalid_request_error", "message": "Invalid JSON"}}),
                        status_code=400, headers={"content-type": "application/json"})

    streaming = body.get("stream", False)
    oai_body = _claude_req_to_oai(body)
    if streaming:
        oai_body["stream"] = True

    api_key = (request.headers.get("x-api-key")
               or request.headers.get("authorization", "").removeprefix("Bearer ").strip())
    oai_bytes = json.dumps(oai_body).encode()
    headers = {
        "content-type": "application/json",
        "content-length": str(len(oai_bytes)),
    }
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"

    model = oai_body.get("model", "")
    ck = _cache_key(model, oai_body.get("messages", []), oai_body.get("tools"))
    log.info("Claude Messages API → model=%s tools=%d stream=%s",
             model, len(oai_body.get("tools", [])), streaming)

    if streaming:
        async def generate():
            if ck:
                cached = await _cache_get(ck)
                if cached is not None:
                    log.info("cache hit (claude stream) key=%s", ck[:16])
                    async for event in _oai_to_claude_stream(_aiter_list(cached), model):
                        yield event
                    return
            buf: list[str] = []
            try:
                async with _client.stream("POST", f"{LITELLM}/v1/chat/completions",
                                          headers=headers, content=oai_bytes) as resp:
                    async for event in _oai_to_claude_stream(_tee_lines(resp.aiter_lines(), buf), model):
                        yield event
            except Exception as exc:
                log.error("Claude stream upstream error model=%s: %s: %s",
                          oai_body.get("model"), type(exc).__name__, exc)
                msg_id = f"msg_{uuid.uuid4().hex[:24]}"
                yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'stop_reason': 'end_turn', 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
                yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
                return
            if ck and buf:
                await _cache_set(ck, buf)
        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (claude) key=%s", ck[:16])
            try:
                return Response(content=json.dumps(
                    _oai_to_claude_resp(json.loads(cached_json[0]))
                ).encode(), status_code=200, headers={"content-type": "application/json"})
            except Exception:
                pass

    resp = await _post_with_retry(f"{LITELLM}/v1/chat/completions", headers, oai_bytes)

    if resp.status_code >= 400:
        log.warning("Claude upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(content=resp.content, status_code=resp.status_code,
                        headers={"content-type": "application/json"})

    try:
        resp_json = resp.json()
        if ck:
            await _cache_set(ck + ":json", [json.dumps(resp_json)])
        claude_resp = _oai_to_claude_resp(resp_json)
        return Response(content=json.dumps(claude_resp).encode(), status_code=200,
                        headers={"content-type": "application/json"})
    except Exception as e:
        log.error("Claude response conversion error: %s", e)
        return Response(content=resp.content, status_code=resp.status_code)


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Catch-all proxy (Cursor / generic OpenAI-compatible clients) ─────────────

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    raw = await request.body()

    body, prefix_stripped = _strip_prefix(raw)
    body, fmt_changed = _patch_body(path, body if prefix_stripped else raw)
    if not fmt_changed and not prefix_stripped:
        body = raw
    changed = prefix_stripped or fmt_changed

    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    if "authorization" not in {k.lower() for k in headers}:
        master_key = os.environ.get("LITELLM_MASTER_KEY", "sk-a3698c2000395d1181397b256415e680")
        headers["authorization"] = f"Bearer {master_key}"
    log.info("Proxy request path: %s headers: %s", path, {k: v for k, v in headers.items() if k.lower() != "authorization"})
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
            try:
                async with _client.stream(
                    request.method, url, headers=headers, content=body, params=params
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        if ck:
                            buf.append(chunk.decode(errors="replace"))
                        yield chunk
            except Exception as exc:
                log.error("Proxy stream upstream error: %s", exc)
            if ck and buf:
                await _cache_set(ck, buf)
        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (proxy) key=%s", ck[:16])
            return Response(content=cached_json[0].encode(), status_code=200,
                            headers={"content-type": "application/json"})

    resp = await _client.request(
        request.method, url, headers=headers, content=body, params=params
    )

    if resp.status_code >= 400:
        log.warning("Upstream %d for %s — raw: %s", resp.status_code, path,
                    raw[:600].decode(errors="replace"))

    if ck and resp.status_code == 200 and is_chat:
        await _cache_set(ck + ":json", [resp.text])

    resp_body = resp.content
    resp_headers = dict(resp.headers)

    if path.rstrip("/") in ("v1/models", "models") and resp.status_code == 200:
        resp_body = _add_prefix_to_models_response(resp_body)
        resp_headers["content-length"] = str(len(resp_body))

    return Response(content=resp_body, status_code=resp.status_code, headers=resp_headers)
