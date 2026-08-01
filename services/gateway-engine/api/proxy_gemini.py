"""Gemini CLI format proxy."""

from __future__ import annotations

import json
import time

from api.policy_hooks import PolicyDeniedError, policy_denial_response
from api.proxy_common import (
    _aiter_list,
    _deps,
    _http_client,
    _main_override,
    _policy_hooks,
    _tee_lines,
    log,
    router,
)
from api.proxy_normalize import _resolve_model
from api.proxy_routing import (
    _auth_fingerprint,
    _extract_and_apply_tenancy,
    _maybe_force_model,
    _post_with_retry,
    _record_cached_token_usage,
    _record_provider_signal,
    _record_token_usage,
    maybe_enqueue_unknown_model_refresh,
)
from fastapi import Request
from fastapi.responses import Response, StreamingResponse
from providers import gemini as gemini_provider
from providers.gemini import get_gemini_map

# ── Gemini format converters (providers.gemini) ──────────────────────────────


def _get_gemini_map() -> dict[str, str]:
    override = _main_override("_get_gemini_map", _get_gemini_map)
    if override is not None:
        return override()
    return get_gemini_map()


GEMINI_FINISH_MAP = gemini_provider.FINISH_MAP
_find_tool_call_id_in_history = gemini_provider._find_tool_call_id_in_history


def _gemini_req_to_oai(model: str, body: dict) -> dict:
    return gemini_provider.req_to_oai(model, body, resolve_model=_resolve_model, gemini_map=_get_gemini_map())


def _oai_to_gemini_resp(oai: dict, model: str) -> dict:
    return gemini_provider.oai_to_resp(oai, model)


async def _gemini_stream(oai_lines):
    async for chunk in gemini_provider.stream(oai_lines):
        yield chunk


@router.api_route("/v1beta/models/{model_action:path}", methods=["GET", "POST"])
async def gemini_proxy(model_action: str, request: Request):
    if request.method == "GET":
        # Pass through to LiteLLM (e.g. model info requests)
        resp = await _http_client().get(
            f"{_deps().litellm_url}/v1beta/models/{model_action}",
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
    try:
        oai_body = await _policy_hooks().apply(auth, oai_body)
    except PolicyDeniedError:
        return policy_denial_response("gemini")
    oai_body = _maybe_force_model(request, oai_body)

    oai_bytes = json.dumps(oai_body).encode()
    headers = {
        "content-type": "application/json",
        "authorization": auth,
        "content-length": str(len(oai_bytes)),
    }

    ck = _deps().cache_key(
        oai_body.get("model", ""),
        oai_body.get("messages", []),
        oai_body.get("tools"),
        auth_fingerprint=_auth_fingerprint(auth),
    )
    log.info(
        "Gemini %s → model=%s tools=%d stream=%s",
        action,
        oai_body["model"],
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
            maybe_enqueue_unknown_model_refresh(resp, model, client_auth=api_key)
            await resp.aclose()
            log.warning(
                "Gemini upstream stream error %d: %s",
                resp.status_code,
                err_content[:300],
            )
            return Response(
                content=err_content,
                status_code=resp.status_code,
                headers=dict(resp.headers),
            )

        async def generate():
            if ck:
                cached = await _deps().cache_get(ck)
                if cached is not None:
                    log.info("cache hit (gemini stream) key=%s", ck[:16])
                    await resp.aclose()
                    async for chunk in _gemini_stream(_aiter_list(cached)):
                        yield chunk
                    return
            buf: list[str] = []
            success = False
            try:
                async for chunk in _gemini_stream(_tee_lines(resp.aiter_lines(), buf)):
                    yield chunk
                success = True
            except Exception as exc:
                log.error(
                    "Gemini stream upstream error model=%s: %s: %s",
                    oai_body.get("model"),
                    type(exc).__name__,
                    exc,
                )
            finally:
                await resp.aclose()
                if success and ck and buf:
                    await _deps().cache_set(ck, buf)

        return StreamingResponse(generate(), media_type="text/event-stream")

        cached_json = await _deps().cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (gemini) key=%s", ck[:16])
            try:
                parsed_cached = json.loads(cached_json[0])
                _record_cached_token_usage(model, parsed_cached, "gateway")
                return Response(
                    content=json.dumps(_oai_to_gemini_resp(parsed_cached, model)).encode(),
                    status_code=200,
                    headers={"content-type": "application/json"},
                )
            except Exception:
                pass

    resp = await _post_with_retry(f"{_deps().litellm_url}/v1/chat/completions", headers, oai_bytes)

    if resp.status_code >= 400:
        maybe_enqueue_unknown_model_refresh(resp, model, client_auth=api_key)
        log.warning("Gemini upstream %d: %s", resp.status_code, resp.text[:300])
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )

    try:
        resp_json = resp.json()
        if ck:
            await _deps().cache_set(ck + ":json", [json.dumps(resp_json)])
        # Record token usage for analytics (#117)
        _record_token_usage(model, resp_json, resp.headers)
        gemini_resp = _oai_to_gemini_resp(resp_json, model)
        return Response(
            content=json.dumps(gemini_resp).encode(),
            status_code=200,
            headers={"content-type": "application/json"},
        )
    except Exception as e:
        log.error("Gemini response conversion error: %s", e)
        return Response(content=resp.content, status_code=resp.status_code)
