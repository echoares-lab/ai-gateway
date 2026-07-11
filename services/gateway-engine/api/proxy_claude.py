"""Claude Messages API converters and proxy."""

from __future__ import annotations

import json
import time
import uuid

from api.proxy_common import (
    _aiter_list,
    _deps,
    _http_client,
    _tee_lines,
    log,
    router,
)
from api.proxy_normalize import _resolve_model
from api.proxy_routing import (
    _apply_policy_engine,
    _auth_fingerprint,
    _extract_and_apply_tenancy,
    _post_with_retry,
    _record_provider_signal,
    _record_token_usage,
)
from fastapi import Request
from fastapi.responses import Response, StreamingResponse
from providers import claude as claude_provider

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


@router.post("/v1/messages")
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
    auth_hdr = headers.get("authorization")
    ck = _deps().cache_key(
        model,
        oai_body.get("messages", []),
        oai_body.get("tools"),
        auth_fingerprint=_auth_fingerprint(auth_hdr),
    )
    log.info(
        "Claude Messages API → model=%s tools=%d stream=%s",
        model,
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
                cached = await _deps().cache_get(ck)
                if cached is not None:
                    log.info("cache hit (claude stream) key=%s", ck[:16])
                    await resp.aclose()
                    async for event in _oai_to_claude_stream(_aiter_list(cached), model):
                        yield event
                    return
            buf: list[str] = []
            success = False
            try:
                async for event in _oai_to_claude_stream(_tee_lines(resp.aiter_lines(), buf), model):
                    yield event
                success = True
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
                if success and ck and buf:
                    await _deps().cache_set(ck, buf)

        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _deps().cache_get(ck + ":json")
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

    resp = await _post_with_retry(f"{_deps().litellm_url}/v1/chat/completions", headers, oai_bytes)

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
            await _deps().cache_set(ck + ":json", [json.dumps(resp_json)])
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
