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
import json
import logging
import os
import time
import uuid
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("translator")

app = FastAPI()
LITELLM = os.environ.get("LITELLM_URL", "http://litellm:4000")
MODEL_PREFIX = "AI-Gateway:"


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
    start = time.monotonic()
    response = await call_next(request)
    ms = (time.monotonic() - start) * 1000
    log.info("[%s] ← %d (%.0fms)", req_id, response.status_code, ms)
    return response


async def _post_with_retry(url: str, headers: dict, content: bytes, retries: int = 2) -> httpx.Response:
    """POST to LiteLLM with retry on transient 502/503."""
    for attempt in range(retries + 1):
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(url, headers=headers, content=content)
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


def _gemini_req_to_oai(model: str, body: dict) -> dict:
    messages = []

    sys_inst = body.get("systemInstruction", {})
    if isinstance(sys_inst, dict):
        sys_text = "".join(p.get("text", "") for p in sys_inst.get("parts", []))
        if sys_text:
            messages.append({"role": "system", "content": sys_text})

    for content in body.get("contents", []):
        role = "assistant" if content.get("role") == "model" else content.get("role", "user")
        parts = content.get("parts", [])

        func_calls = [p["functionCall"] for p in parts if "functionCall" in p]
        func_resps = [p["functionResponse"] for p in parts if "functionResponse" in p]
        texts = [p.get("text", "") for p in parts if "text" in p]
        inline = [p for p in parts if "inlineData" in p or "fileData" in p]

        if func_resps:
            for fr in func_resps:
                messages.append({
                    "role": "tool",
                    "tool_call_id": fr["name"],
                    "content": json.dumps(fr.get("response", {})),
                })
        elif func_calls:
            tool_calls = []
            for fc in func_calls:
                tool_calls.append({
                    "id": fc["name"],
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

    oai = {"model": _get_gemini_map().get(model, model), "messages": messages}

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
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{LITELLM}/v1beta/models/{model_action}",
                                    params=dict(request.query_params))
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

    log.info("Gemini %s → model=%s tools=%d stream=%s",
             action, oai_body["model"], len(oai_body.get("tools", [])), streaming)

    if streaming:
        async def generate():
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", f"{LITELLM}/v1/chat/completions",
                                         headers=headers, content=oai_bytes) as resp:
                    async for chunk in _gemini_stream(resp.aiter_lines()):
                        yield chunk
        return StreamingResponse(generate(), media_type="text/event-stream")

    resp = await _post_with_retry(f"{LITELLM}/v1/chat/completions", headers, oai_bytes)

    if resp.status_code >= 400:
        log.warning("Gemini upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(content=resp.content, status_code=resp.status_code,
                        headers={"content-type": "application/json"})

    try:
        gemini_resp = _oai_to_gemini_resp(resp.json(), model)
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

    oai: dict = {"model": body.get("model", ""), "messages": messages}

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
    headers["content-type"] = "application/json"
    headers["content-length"] = str(len(oai_bytes))

    log.info("Codex Responses API → model=%s tools=%d stream=%s",
             oai_body.get("model"), len(oai_body.get("tools", [])), streaming)

    if streaming:
        async def generate():
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", f"{LITELLM}/v1/chat/completions",
                                         headers=headers, content=oai_bytes) as resp:
                    async for event in _oai_to_responses_stream(resp.aiter_lines()):
                        yield event
        return StreamingResponse(generate(), media_type="text/event-stream")

    resp = await _post_with_retry(f"{LITELLM}/v1/chat/completions", headers, oai_bytes)

    if resp.status_code >= 400:
        log.warning("Codex upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(content=resp.content, status_code=resp.status_code,
                        headers={"content-type": "application/json"})

    try:
        responses_resp = _oai_to_responses_resp(resp.json())
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
    messages = []

    system = body.get("system", "")
    if isinstance(system, list):
        system = "".join(b.get("text", "") for b in system if b.get("type") == "text")
    if system:
        messages.append({"role": "system", "content": system})

    for msg in body.get("messages", []):
        messages.extend(_claude_msg_to_oai(msg))

    oai: dict = {
        "model": body.get("model", ""),
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
        "authorization": f"Bearer {api_key}",
        "content-length": str(len(oai_bytes)),
    }

    model = oai_body.get("model", "")
    log.info("Claude Messages API → model=%s tools=%d stream=%s",
             model, len(oai_body.get("tools", [])), streaming)

    if streaming:
        async def generate():
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", f"{LITELLM}/v1/chat/completions",
                                         headers=headers, content=oai_bytes) as resp:
                    async for event in _oai_to_claude_stream(resp.aiter_lines(), model):
                        yield event
        return StreamingResponse(generate(), media_type="text/event-stream")

    resp = await _post_with_retry(f"{LITELLM}/v1/chat/completions", headers, oai_bytes)

    if resp.status_code >= 400:
        log.warning("Claude upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(content=resp.content, status_code=resp.status_code,
                        headers={"content-type": "application/json"})

    try:
        claude_resp = _oai_to_claude_resp(resp.json())
        return Response(content=json.dumps(claude_resp).encode(), status_code=200,
                        headers={"content-type": "application/json"})
    except Exception as e:
        log.error("Claude response conversion error: %s", e)
        return Response(content=resp.content, status_code=resp.status_code)


# ── Catch-all proxy (Cursor / generic OpenAI-compatible clients) ─────────────

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    raw = await request.body()

    body, prefix_stripped = _strip_prefix(raw)
    body, fmt_changed = _patch_body(path, body if prefix_stripped else raw)
    if not fmt_changed and prefix_stripped:
        body = body
    elif not fmt_changed and not prefix_stripped:
        body = raw
    changed = prefix_stripped or fmt_changed

    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    if changed:
        headers["content-length"] = str(len(body))

    is_stream = False
    try:
        is_stream = json.loads(body).get("stream", False)
    except Exception:
        pass

    url = f"{LITELLM}/{path}"
    params = dict(request.query_params)

    if is_stream:
        async def generate():
            try:
                async with httpx.AsyncClient(timeout=300) as client:
                    async with client.stream(
                        request.method, url, headers=headers, content=body, params=params
                    ) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            except httpx.HTTPError as exc:
                log.error("Proxy stream connection error: %s", exc)
        return StreamingResponse(generate(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.request(
            request.method, url, headers=headers, content=body, params=params
        )

    if resp.status_code >= 400:
        log.warning("Upstream %d for %s — raw: %s", resp.status_code, path,
                    raw[:600].decode(errors="replace"))

    resp_body = resp.content
    resp_headers = dict(resp.headers)

    if path.rstrip("/") in ("v1/models", "models") and resp.status_code == 200:
        resp_body = _add_prefix_to_models_response(resp_body)
        resp_headers["content-length"] = str(len(resp_body))

    return Response(content=resp_body, status_code=resp.status_code, headers=resp_headers)
