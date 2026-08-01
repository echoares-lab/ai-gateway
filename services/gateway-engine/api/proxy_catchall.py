"""Catch-all OpenAI-compatible proxy."""

from __future__ import annotations

import json
import time

import httpx
from api.proxy_common import (
    _deps,
    _enable_virtual_providers,
    _http_client,
    _log_safe_headers,
    _policy_hooks,
    log,
)
from api.proxy_normalize import (
    _add_prefix_to_models_response,
    _patch_body,
    _strip_prefix,
)
from api.proxy_routing import (
    _auth_fingerprint,
    _extract_and_apply_tenancy,
    _maybe_force_model,
    _model_from_content,
    _normalize_upstream_authorization,
    _record_provider_signal,
    maybe_enqueue_unknown_model_refresh,
)
from core.policy.client_detector import client_detector
from fastapi import Request
from fastapi.responses import Response, StreamingResponse
from providers.virtual import virtual_provider

# Registered last by proxy_router facade (must not use @router decorator here).


async def proxy(path: str, request: Request):
    raw = await request.body()
    client_auth = next(
        (
            value
            for value in (
                request.headers.get("authorization"),
                request.headers.get("x-api-key"),
                request.headers.get("x-goog-api-key"),
                request.headers.get("api-key"),
                request.query_params.get("key"),
            )
            if value and value.strip()
        ),
        None,
    )

    body, prefix_stripped = _strip_prefix(raw)
    body, fmt_changed = _patch_body(path, body if prefix_stripped else raw)
    if not fmt_changed and not prefix_stripped:
        body = raw
    changed = prefix_stripped or fmt_changed

    integration_profile = client_detector.detect(request)
    log.debug(
        "Detected integration profile: %s",
        integration_profile.get("client_name") if integration_profile else "none",
    )

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
            bd = await _policy_hooks().apply(auth_token, bd)
            bd = _maybe_force_model(request, bd)
            body = json.dumps(bd).encode()
            changed = True
        except Exception as exc:
            log.warning("tenancy/policy apply failed — fail-open: %s", exc)

    headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}

    if integration_profile and "inject_headers" in integration_profile.get("config", {}):
        headers.update(integration_profile["config"]["inject_headers"])

    _normalize_upstream_authorization(headers)
    log.info(
        "Proxy request path: %s headers: %s",
        path,
        _log_safe_headers(headers),
    )
    if changed:
        headers["content-length"] = str(len(body))

    is_stream = False
    try:
        is_stream = json.loads(body).get("stream", False)
    except Exception:
        pass

    url = f"{_deps().litellm_url}/{path}"
    params = dict(request.query_params)

    # Cache only chat completion POST requests
    ck = None
    is_chat = path.rstrip("/") in ("v1/chat/completions", "chat/completions")
    if is_chat and request.method == "POST":
        try:
            bd = json.loads(body)
            ck = _deps().cache_key(
                bd.get("model", ""),
                bd.get("messages", []),
                bd.get("tools"),
                auth_fingerprint=_auth_fingerprint(headers.get("authorization")),
            )
        except Exception:
            pass

    signal_model = _model_from_content(body) if is_chat else ""

    if is_stream:
        if ck:
            cached = await _deps().cache_get(ck)
            if cached is not None:
                log.info("cache hit (proxy stream) key=%s", ck[:16])

                async def cached_generate():
                    for line in cached:
                        yield (line + "\n").encode()

                return StreamingResponse(cached_generate(), media_type="text/event-stream")

        start = time.monotonic()
        stream_context = _http_client().stream(request.method, url, headers=headers, content=body, params=params)
        try:
            resp = await stream_context.__aenter__()
        except Exception as exc:
            is_timeout = isinstance(exc, httpx.TimeoutException)
            log.error("Proxy stream upstream error for %s: %s", path, exc)
            failure_message = (
                f"Upstream request timed out after {_deps().upstream_timeout} seconds"
                if is_timeout
                else f"Upstream connection failed: {exc}"
            )

            async def failed_generate():
                err = {
                    "error": {
                        "message": failure_message,
                        "type": "timeout_error" if is_timeout else "connection_error",
                    }
                }
                yield ("data: " + json.dumps(err) + "\n\n").encode()

            return StreamingResponse(failed_generate(), media_type="text/event-stream")

        if is_chat:
            _record_provider_signal(signal_model, resp.status_code, time.monotonic() - start)
        if resp.status_code >= 400:
            err_content = await resp.aread()
            maybe_enqueue_unknown_model_refresh(resp, signal_model, client_auth=client_auth)
            await stream_context.__aexit__(None, None, None)
            log.warning(
                "Proxy upstream stream error %d for %s: %s",
                resp.status_code,
                path,
                err_content[:300],
            )
            return Response(content=err_content, status_code=resp.status_code, headers=dict(resp.headers))

        async def generate():
            buf: list[str] = []
            success = False
            try:
                async for chunk in resp.aiter_bytes():
                    if ck:
                        buf.append(chunk.decode(errors="replace"))
                    yield chunk
                success = True
            except httpx.TimeoutException as exc:
                log.error("Proxy stream upstream timed out for %s: %s", path, exc)
                err = {
                    "error": {
                        "message": f"Upstream request timed out after {_deps().upstream_timeout} seconds",
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
            finally:
                await stream_context.__aexit__(None, None, None)
            if success and ck and buf:
                await _deps().cache_set(ck, buf)

        return StreamingResponse(generate(), media_type="text/event-stream")

    if ck:
        cached_json = await _deps().cache_get(ck + ":json")
        if cached_json is not None:
            log.info("cache hit (proxy) key=%s", ck[:16])
            return Response(
                content=cached_json[0].encode(),
                status_code=200,
                headers={"content-type": "application/json"},
            )

    _proxy_start = time.monotonic()

    if _enable_virtual_providers() and signal_model.startswith("virt-"):
        parts = signal_model.split("-")
        status_code = 200
        if len(parts) >= 3 and parts[1] == "error":
            try:
                status_code = int(parts[2])
            except ValueError:
                pass

        try:
            req_body = json.loads(body)
        except Exception:
            req_body = {}

        if status_code == 200:
            v_resp = virtual_provider.oai_to_resp(req_body, signal_model)
        else:
            v_resp = virtual_provider.simulate_error(status_code)

        elapsed = time.monotonic() - _proxy_start
        if is_chat:
            _record_provider_signal(signal_model, status_code, elapsed)

        resp_body = json.dumps(v_resp).encode("utf-8")
        if ck and status_code == 200 and is_chat:
            await _deps().cache_set(ck + ":json", [resp_body.decode("utf-8")])

        return Response(content=resp_body, status_code=status_code, headers={"content-type": "application/json"})

    try:
        resp = await _http_client().request(request.method, url, headers=headers, content=body, params=params)
    except httpx.TimeoutException as exc:
        log.error("Proxy upstream timed out for %s: %s", path, exc)
        return Response(
            content=json.dumps(
                {
                    "error": {
                        "message": f"Upstream request timed out after {_deps().upstream_timeout} seconds",
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
        maybe_enqueue_unknown_model_refresh(
            resp,
            signal_model,
            client_auth=client_auth,
        )
        log.warning(
            "Upstream %d for %s — raw: %s",
            resp.status_code,
            path,
            raw[:600].decode(errors="replace"),
        )

    if ck and resp.status_code == 200 and is_chat:
        await _deps().cache_set(ck + ":json", [resp.text])

    resp_body = resp.content
    resp_headers = dict(resp.headers)

    if path.rstrip("/") in ("v1/models", "models") and resp.status_code == 200:
        resp_body = _add_prefix_to_models_response(resp_body)
        resp_headers["content-length"] = str(len(resp_body))

    return Response(content=resp_body, status_code=resp.status_code, headers=resp_headers)
