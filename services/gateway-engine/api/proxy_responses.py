"""OpenAI Responses API converters and proxy."""

from __future__ import annotations

import json
import time
import uuid

import httpx
from api.proxy_common import (
    _aiter_list,
    _deps,
    _http_client,
    _tee_lines,
    log,
    router,
)
from api.proxy_normalize import (
    _normalize_tools,
    _resolve_model,
    _responses_input_to_messages,
)
from api.proxy_routing import (
    _apply_policy_engine,
    _auth_fingerprint,
    _extract_and_apply_tenancy,
    _maybe_force_model,
    _normalize_upstream_authorization,
    _post_with_retry,
    _record_provider_signal,
    _record_token_usage,
)
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

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
            "input_tokens_details": {
                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            },
            "output_tokens_details": {
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
            },
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


@router.post("/v1/responses")
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
    oai_body = _maybe_force_model(request, oai_body)

    oai_bytes = json.dumps(oai_body).encode()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length", "content-type")}
    _normalize_upstream_authorization(headers)
    headers["content-type"] = "application/json"
    headers["content-length"] = str(len(oai_bytes))

    ck = _deps().cache_key(
        oai_body.get("model", ""),
        oai_body.get("messages", []),
        oai_body.get("tools"),
        auth_fingerprint=_auth_fingerprint(auth or headers.get("authorization")),
    )
    log.info("Codex request headers: %s", {k: v for k, v in request.headers.items()})
    log.info(
        "Codex Responses API → model=%s tools=%d stream=%s",
        oai_body.get("model"),
        len(oai_body.get("tools", [])),
        streaming,
    )

    if streaming:
        req = _http_client().build_request(
            "POST", f"{_deps().litellm_url}/v1/chat/completions", headers=headers, content=oai_bytes
        )
        try:
            _sig_start = time.monotonic()
            resp = await _http_client().send(req, stream=True)
            _record_provider_signal(
                oai_body.get("model", "-"),
                resp.status_code,
                time.monotonic() - _sig_start,
            )
        except httpx.TimeoutException as exc:
            log.error("Responses stream upstream timed out: %s", exc)
            err_msg = (
                f"Upstream request timed out after {_deps().upstream_timeout} seconds. Please check LiteLLM readiness."
            )
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
                cached = await _deps().cache_get(ck)
                if cached is not None:
                    log.info("cache hit (responses stream) key=%s", ck[:16])
                    await resp.aclose()
                    async for event in _oai_to_responses_stream(_aiter_list(cached)):
                        yield event
                    return
            buf: list[str] = []
            success = False
            try:
                async for event in _oai_to_responses_stream(_tee_lines(resp.aiter_lines(), buf)):
                    yield event
                success = True
            except httpx.TimeoutException as exc:
                log.error("Responses stream upstream timed out: %s", exc)
                err_id = f"resp_{uuid.uuid4().hex[:24]}"
                err_msg = f"Upstream request timed out after {_deps().upstream_timeout} seconds. Please check LiteLLM readiness."
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
                if success and ck and buf:
                    await _deps().cache_set(ck, buf)

        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _deps().cache_get(ck + ":json")
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
        resp = await _post_with_retry(f"{_deps().litellm_url}/v1/chat/completions", headers, oai_bytes)
    except httpx.TimeoutException as exc:
        log.error("Codex upstream request timed out: %s", exc)
        err_msg = (
            f"Upstream request timed out after {_deps().upstream_timeout} seconds. Please check LiteLLM readiness."
        )
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
            await _deps().cache_set(ck + ":json", [json.dumps(resp_json)])
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
