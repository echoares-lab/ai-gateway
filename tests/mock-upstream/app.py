"""Canned OpenAI-compatible upstream standing in for CLIProxyAPI.

No OAuth, no real LLM. Returns deterministic 200s so the translator's
wire-format translation runs end-to-end (translator -> litellm -> here).
When the request carries `tools`, the mock returns a tool_calls completion so
the translator's response-side tool translation (OAI tool_calls -> Claude
`tool_use` / Gemini `functionCall` / Responses `function_call`) is exercised
too.

Run standalone:
    uvicorn app:app --host 0.0.0.0 --port 8317
"""

import json
import time
import uuid

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/models")
def models():
    # Mirror a few names LiteLLM forwards (post model-name mapping).
    return {
        "object": "list",
        "data": [
            {"id": "claude-sonnet-4-6", "object": "model"},
            {"id": "gpt-5.3-codex", "object": "model"},
            {"id": "gemini-2.5-flash", "object": "model"},
        ],
    }


def _has_tools(body: dict) -> bool:
    return bool(body.get("tools"))


def _completion(model: str, with_tool: bool) -> dict:
    if with_tool:
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_mock",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": json.dumps({"location": "NYC"}),
                    },
                }
            ],
        }
        finish = "tool_calls"
    else:
        msg = {"role": "assistant", "content": "OK"}
        finish = "stop"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _sse(model: str, with_tool: bool):
    cid = f"chatcmpl-{uuid.uuid4().hex[:8]}"

    def chunk(delta: dict, finish=None) -> str:
        return (
            "data: "
            + json.dumps(
                {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
            )
            + "\n\n"
        )

    yield chunk({"role": "assistant"})
    if with_tool:
        yield chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_mock",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": json.dumps({"location": "NYC"}),
                        },
                    }
                ]
            }
        )
        yield chunk({}, "tool_calls")
    else:
        yield chunk({"content": "OK"})
        yield chunk({}, "stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    model = body.get("model", "mock-model")
    with_tool = _has_tools(body)
    if body.get("stream"):
        return StreamingResponse(_sse(model, with_tool), media_type="text/event-stream")
    return JSONResponse(_completion(model, with_tool))


def _responses_payload(model: str, with_tool: bool) -> dict:
    if with_tool:
        output = [
            {
                "type": "function_call",
                "id": "fc_mock",
                "call_id": "call_mock",
                "name": "get_weather",
                "arguments": json.dumps({"location": "NYC"}),
                "status": "completed",
            }
        ]
    else:
        output = [
            {
                "type": "message",
                "id": "msg_mock",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "OK", "annotations": []}],
            }
        ]
    # Full ResponsesAPIResponse shape — LiteLLM's parser requires created_at and
    # the surrounding fields, so a minimal object trips KeyError/OpenAIError.
    return {
        "id": "resp_mock",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": model,
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "temperature": 1.0,
        "text": {"format": {"type": "text"}},
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "user": None,
        "metadata": {},
        "store": False,
    }


@app.post("/v1/responses")
async def responses(request: Request):
    # LiteLLM routes Responses-native models (e.g. codex) to upstream
    # /v1/responses, so this must return a full, parseable ResponsesAPIResponse.
    body = await request.json()
    model = body.get("model", "mock")
    with_tool = _has_tools(body)
    if body.get("stream"):
        return StreamingResponse(_responses_sse(model, with_tool), media_type="text/event-stream")
    return JSONResponse(_responses_payload(model, with_tool))


def _responses_sse(model: str, with_tool: bool):
    payload = _responses_payload(model, with_tool)
    rid = payload["id"]
    yield "event: response.created\n"
    yield "data: " + json.dumps({"type": "response.created", "response": {"id": rid, "status": "in_progress"}}) + "\n\n"
    if not with_tool:
        yield "event: response.output_text.delta\n"
        yield "data: " + json.dumps({"type": "response.output_text.delta", "delta": "OK"}) + "\n\n"
    yield "event: response.completed\n"
    yield "data: " + json.dumps({"type": "response.completed", "response": payload}) + "\n\n"


@app.post("/v1/responses/compact")
async def responses_compact(request: Request):
    # Simulate Responses compaction endpoint
    body = await request.json()
    model = body.get("model", "mock")
    return JSONResponse({
        "id": "resp_compact_mock",
        "object": "response.compaction",
        "created_at": int(time.time()),
        "model": model,
        "output": []
    })


@app.websocket("/v1/responses")
async def responses_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                # Simulate Responses API events
                await websocket.send_text(json.dumps({
                    "type": "response.created", 
                    "response": {"id": "resp_ws_mock", "status": "in_progress"}
                }))
                await websocket.send_text(json.dumps({
                    "type": "response.output_text.delta", 
                    "delta": "Hello from WS!"
                }))
                payload = _responses_payload("gpt-5.3-codex", False)
                await websocket.send_text(json.dumps({
                    "type": "response.completed", 
                    "response": payload
                }))
            except Exception:
                await websocket.send_text(json.dumps({
                    "type": "response.output_text.delta", 
                    "delta": f"echo: {data}"
                }))
    except WebSocketDisconnect:
        pass
