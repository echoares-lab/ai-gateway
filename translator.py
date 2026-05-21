"""
Thin proxy that sits in front of LiteLLM and translates OpenAI Responses API
requests (used by Cursor Agent mode) into Chat Completions format.

Cursor Agent mode sends requests with `input` instead of `messages` to
/v1/chat/completions. This proxy converts `input` → `messages` so LiteLLM
can route them correctly.
"""
import json
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

app = FastAPI()
LITELLM = "http://litellm:4000"


def _input_to_messages(inp: object) -> list:
    if isinstance(inp, str):
        return [{"role": "user", "content": inp}]
    if isinstance(inp, list):
        msgs = []
        for item in inp:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message" or ("role" in item and "content" in item):
                msgs.append({"role": item.get("role", "user"), "content": item.get("content", "")})
        return msgs
    return []


def _patch_body(path: str, body: bytes) -> bytes:
    if path.rstrip("/") not in ("v1/chat/completions", "chat/completions"):
        return body
    try:
        data = json.loads(body)
    except Exception:
        return body
    if "messages" not in data and "input" in data:
        data["messages"] = _input_to_messages(data.pop("input"))
        return json.dumps(data).encode()
    return body


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(path: str, request: Request):
    raw = await request.body()
    body = _patch_body(path, raw)

    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
    if len(body) != len(raw):
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
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )
