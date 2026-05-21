"""
Translation proxy: converts OpenAI Responses API format (used by Cursor Agent
mode) to Chat Completions format before forwarding to LiteLLM.

Handles all known Responses API input types:
  input_text / output_text → {"type": "text", "text": "..."}
  input_image              → {"type": "image_url", "image_url": {...}}
  input_file               → {"type": "text", "text": "..."} (best-effort)
  function_call            → assistant message with tool_calls
  function_call_output     → tool message
  message                  → standard Chat Completions message

Also normalises content arrays in requests that already use `messages` but
contain Responses API content types (e.g. input_text).

Model prefixing:
  GET /v1/models response  → all model IDs prefixed with MODEL_PREFIX
  POST /v1/chat/completions → MODEL_PREFIX stripped from `model` field
  This lets Cursor distinguish gateway models from its own built-in ones.
"""
import json
import logging
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("translator")

app = FastAPI()
LITELLM = "http://litellm:4000"
MODEL_PREFIX = "AI-Gateway:"

# ── Content normalisation ────────────────────────────────────────────────────

def _normalize_content_item(c: dict) -> dict | None:
    """Convert a single Responses API content block to Chat Completions form."""
    ct = c.get("type", "")

    # Text variants
    if ct in ("input_text", "output_text", "text", "refusal"):
        return {"type": "text", "text": c.get("text", c.get("refusal", ""))}

    # Image
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
        return None  # can't convert, skip

    # File — best-effort as text
    if ct == "input_file":
        text = c.get("text") or c.get("filename") or "[file]"
        return {"type": "text", "text": text}

    # Pass unknown types through unchanged
    return c


def _normalize_content(content):
    """
    Normalize a Responses API content value to Chat Completions format.
    Returns a plain string when all parts are text-only, otherwise a list.
    """
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

    # Flatten to a plain string when everything is text
    if all(c.get("type") == "text" for c in normalized):
        return "".join(c.get("text", "") for c in normalized)
    return normalized


# ── Responses API input → Chat Completions messages ─────────────────────────

def _responses_input_to_messages(inp) -> list:
    """Convert a Responses API `input` value to a Chat Completions messages list."""
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

            # Check for tool-use blocks inside the content
            if isinstance(content, list):
                tool_blocks = [
                    c for c in content
                    if isinstance(c, dict) and c.get("type") in ("tool_use", "function_call")
                ]
                if tool_blocks:
                    # Assistant message with tool calls
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
            # Standalone function_call item → buffer into pending tool calls
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


# ── Message normalisation (when `messages` already present) ──────────────────

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


# ── Tool normalisation ───────────────────────────────────────────────────────

def _normalize_tools(tools: list) -> tuple[list, bool]:
    """
    Convert Responses API tool format to Chat Completions format.

    Responses API:  {type: "function", name: "...", description: "...", parameters: {...}}
    Chat Completions: {type: "function", function: {name: "...", description: "...", parameters: {...}}}
    """
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


# ── Model prefix ─────────────────────────────────────────────────────────────

def _strip_prefix(body: bytes) -> tuple[bytes, bool]:
    """Strip MODEL_PREFIX from the `model` field in a request body."""
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
    """Prefix all model IDs in a /v1/models response with MODEL_PREFIX."""
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


# ── Body patching ────────────────────────────────────────────────────────────

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


# ── Proxy ────────────────────────────────────────────────────────────────────

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    raw = await request.body()

    # Strip model prefix before format patching
    body, prefix_stripped = _strip_prefix(raw)
    body, fmt_changed = _patch_body(path, body if prefix_stripped else raw)
    if not fmt_changed and prefix_stripped:
        body = body  # already set by _strip_prefix
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
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream(
                    request.method, url, headers=headers, content=body, params=params
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk

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

    # Add model prefix to /v1/models response
    if path.rstrip("/") in ("v1/models", "models") and resp.status_code == 200:
        resp_body = _add_prefix_to_models_response(resp_body)
        resp_headers["content-length"] = str(len(resp_body))

    return Response(content=resp_body, status_code=resp.status_code, headers=resp_headers)
