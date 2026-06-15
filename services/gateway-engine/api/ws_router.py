import asyncio
import inspect
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import websockets
from fastapi import APIRouter, WebSocket

log = logging.getLogger("gateway-engine")


@dataclass(frozen=True)
class WsRouterDeps:
    admin_redact: Callable[[str], tuple[str, bool]]
    build_routing_context: Callable[[WebSocket, str | None], dict[str, Any]]
    evaluate_policy_engine: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]
    upstream_timeout: float


def _policy_engine_enabled() -> bool:
    return os.environ.get("POLICY_ENGINE_ENABLED", "").lower() in ("1", "true", "yes")


def _policy_engine_ws_evaluate_enabled() -> bool:
    return os.environ.get("POLICY_ENGINE_WS_EVALUATE", "").lower() in (
        "1",
        "true",
        "yes",
    )


def codex_ws_policy_bypass() -> bool:
    """True when Codex WS upgrade skips policy-engine evaluate (default)."""
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


def _parse_ws_client_auth(ws: WebSocket) -> str:
    client_auth = ws.headers.get("authorization", "")
    if not client_auth:
        client_auth = ws.headers.get("api-key", "")
    if not client_auth:
        client_auth = ws.query_params.get("key", "")
    return client_auth


def _validate_ws_auth_token(client_auth: str) -> tuple[bool, str | None]:
    """Return (authorized, normalized_token). Fail closed when auth is missing."""
    if not client_auth:
        return False, None
    auth_token = client_auth[7:] if client_auth.startswith("Bearer ") else client_auth
    expected_master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if expected_master_key and auth_token == expected_master_key:
        return True, auth_token
    if auth_token.startswith("sk-") and len(auth_token) >= 10:
        return True, auth_token
    return False, auth_token


async def _litellm_virtual_key_valid(auth_token: str) -> bool:
    """Verify sk-* token against LiteLLM key/info (issue #307)."""
    litellm_url = os.environ.get("LITELLM_URL", "http://litellm:4000").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{litellm_url}/key/info",
                params={"key": auth_token},
                headers={"Authorization": f"Bearer {auth_token}"},
            )
            return resp.status_code == 200
    except Exception as exc:
        log.warning("LiteLLM key validation failed: %s", type(exc).__name__)
        return False


async def _validate_ws_auth_token_async(client_auth: str) -> tuple[bool, str | None]:
    ok, auth_token = _validate_ws_auth_token(client_auth)
    if not ok or not auth_token:
        return ok, auth_token
    master = os.environ.get("LITELLM_MASTER_KEY", "")
    if auth_token == master:
        return True, auth_token
    if auth_token.startswith("sk-"):
        if await _litellm_virtual_key_valid(auth_token):
            return True, auth_token
        return False, auth_token
    return ok, auth_token


def _ws_log_safe_mapping(values: dict[str, str]) -> dict[str, str]:
    auth_keys = frozenset({"authorization", "api-key", "x-api-key", "key"})
    safe: dict[str, str] = {}
    for key, value in values.items():
        if key.lower() in auth_keys:
            safe[key] = "[redacted]"
        else:
            safe[key] = value
    return safe


def create_ws_router(deps: WsRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.websocket("/v1/responses")
    async def responses_websocket(ws: WebSocket):
        # Accept client WebSocket connection
        await ws.accept()

        log.info("WebSocket headers: %s", _ws_log_safe_mapping(dict(ws.headers)))
        log.info("WebSocket query params: %s", _ws_log_safe_mapping(dict(ws.query_params)))

        client_auth = _parse_ws_client_auth(ws)
        is_authorized, auth_token = await _validate_ws_auth_token_async(client_auth)

        if not is_authorized:
            redacted_auth, _ = deps.admin_redact(client_auth) if client_auth else ("", False)
            log.warning(
                "Unauthorized Codex WebSocket connection attempt (auth_present=%s)",
                bool(client_auth),
            )
            if client_auth:
                log.debug("Unauthorized WebSocket token (redacted): %s", redacted_auth)
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
            policy_token = auth_token if client_auth else None
            ctx = deps.build_routing_context(ws, policy_token)
            routing_decision = await deps.evaluate_policy_engine(ctx)
            log.info(
                "Codex WebSocket in-process policy evaluate completed (gate=%s)",
                routing_decision.get("gate") if routing_decision else "none",
            )

        headers = _codex_ws_upstream_headers(dict(ws.headers), routing_decision)

        log.info(
            "Proxying Codex WebSocket to upstream: %s (policy_bypass=%s)",
            cliproxy_ws_url,
            ws_bypass,
        )
        try:
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
                                timeout_val = deps.upstream_timeout if not received_any else 15.0
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
                                        "message": (
                                            f"Upstream WebSocket connection timed out after {deps.upstream_timeout}s."
                                        ),
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
                _done, pending = await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
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

    return router
