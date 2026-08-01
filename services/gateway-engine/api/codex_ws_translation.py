"""Opt-in Codex WebSocket frame translation.

The normal WebSocket path remains the byte-preserving CLIProxy proxy.  This
module is entered only when ``CODEX_WS_TRANSLATION_ENABLED`` is true and the
client negotiates ``codex-ws.v1``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

log = logging.getLogger("gateway-engine")

SUBPROTOCOL = "codex-ws.v1"
MAX_FRAME_BYTES = 64 * 1024
MAX_VALUE_BYTES = 32 * 1024
MAX_IN_FLIGHT = 16
MAX_QUEUE = 128
REQUEST_TIMEOUT_SECONDS = 30.0
IDLE_TIMEOUT_SECONDS = 120.0
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_CLIENT_TYPES = {"request.start", "request.delta", "request.cancel"}
_SERVER_TYPES = {"response.delta", "response.tool_call", "response.completed", "response.error"}


class ProtocolError(ValueError):
    """A client frame failed deterministic protocol validation."""


def enabled() -> bool:
    """Whether the translator is enabled (off by default)."""
    return os.environ.get("CODEX_WS_TRANSLATION_ENABLED", "").lower() in {"1", "true", "yes"}


def requested(ws: WebSocket) -> bool:
    """Return true when the client requested the translator subprotocol."""
    offered = ws.scope.get("subprotocols") or []
    if not offered:
        offered = [item.strip() for item in ws.headers.get("sec-websocket-protocol", "").split(",") if item.strip()]
    return SUBPROTOCOL in offered


def active(ws: WebSocket) -> bool:
    return enabled() and requested(ws)


def _encoded_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _bounded_string(value: Any, name: str, maximum: int = MAX_VALUE_BYTES) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > maximum:
        raise ProtocolError(f"invalid_{name}")
    return value


def _request_id(value: Any) -> str:
    if not isinstance(value, str) or not REQUEST_ID_RE.fullmatch(value):
        raise ProtocolError("invalid_request_id")
    return value


def _sequence(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value >= 2**53:
        raise ProtocolError("invalid_sequence")
    return value


def _safe_message(code: str) -> str:
    return {
        "protocol_error": "invalid WebSocket frame",
        "message_too_large": "message too large",
        "rate_limited": "request limit reached",
        "timeout": "upstream request timed out",
        "upstream_unavailable": "upstream unavailable",
        "cancelled": "request cancelled",
        "translation_error": "translation failed",
        "policy_denied": "request denied by policy",
    }.get(code, "request failed")


def decode_frame(data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Decode a Starlette WebSocket receive payload and return frame/hash."""
    if data.get("type") == "websocket.disconnect":
        raise EOFError
    value = data.get("text")
    if value is None:
        raw = data.get("bytes")
        if not isinstance(raw, bytes):
            raise ProtocolError("protocol_error")
        if len(raw) > MAX_FRAME_BYTES:
            raise ProtocolError("message_too_large")
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("protocol_error") from exc
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_FRAME_BYTES:
        raise ProtocolError("message_too_large")
    try:
        frame = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("protocol_error") from exc
    if not isinstance(frame, dict) or not isinstance(frame.get("type"), str):
        raise ProtocolError("protocol_error")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return frame, digest


def validate_client_frame(frame: dict[str, Any]) -> None:
    frame_type = frame.get("type")
    if frame_type not in _CLIENT_TYPES:
        raise ProtocolError("protocol_error")
    request_id = _request_id(frame.get("request_id"))
    del request_id
    if frame_type == "request.start":
        if not isinstance(frame.get("model"), str) or not frame["model"].strip():
            raise ProtocolError("invalid_model")
        _bounded_string(frame["model"], "model", 1024)
        if "input" not in frame or _encoded_size(frame["input"]) > MAX_VALUE_BYTES:
            raise ProtocolError("invalid_input")
        return
    _sequence(frame.get("sequence"))
    if frame_type == "request.delta":
        if "delta" not in frame or _encoded_size(frame["delta"]) > MAX_VALUE_BYTES:
            raise ProtocolError("invalid_delta")
    elif "reason" in frame:
        _bounded_string(frame["reason"], "reason", 1024)


@dataclass
class RequestState:
    request_id: str
    last_sequence: int = -1
    terminal: bool = False
    seen: dict[int, str] = field(default_factory=dict)
    output_sequence: int = -1


class CodexWsTranslator:
    """Bounded bidirectional translator for a single negotiated connection."""

    def __init__(self, ws: WebSocket, upstream: Any, first_frame: dict[str, Any] | None = None):
        self.ws = ws
        self.upstream = upstream
        self.first_frame = first_frame
        self.states: dict[str, RequestState] = {}
        self._send_lock = asyncio.Lock()
        self._closed = False

    async def _send_client(self, frame: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.ws.send_text(json.dumps(frame, separators=(",", ":")))

    async def _error(self, request_id: str | None, code: str, *, close: int | None = None) -> None:
        frame: dict[str, Any] = {"type": "response.error", "code": code, "message": _safe_message(code)}
        if request_id:
            state = self.states.get(request_id)
            frame["request_id"] = request_id
            frame["sequence"] = (state.output_sequence + 1) if state else 0
            if state:
                state.output_sequence = frame["sequence"]
                state.terminal = True
        await self._send_client(frame)
        if close is not None:
            await self._close(close, _safe_message(code))

    async def _close(self, code: int, reason: str) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.ws.close(code=code, reason=reason)
        except Exception:
            pass

    async def _send_upstream(self, frame: dict[str, Any]) -> None:
        await self.upstream.send(json.dumps(frame, separators=(",", ":")))

    async def _client_frame(self, frame: dict[str, Any], digest: str) -> None:
        validate_client_frame(frame)
        request_id = frame["request_id"]
        state = self.states.get(request_id)
        if frame["type"] == "request.start":
            if state is not None:
                if state.seen.get(-1) == digest:
                    return
                raise ProtocolError("protocol_error")
            if len(self.states) >= MAX_IN_FLIGHT:
                await self._error(request_id, "rate_limited")
                return
            state = RequestState(request_id=request_id)
            state.seen[-1] = digest
            self.states[request_id] = state
            await self._send_upstream(
                {"type": "response.create", "request_id": request_id, "model": frame["model"], "input": frame["input"]}
            )
            return
        if state is None:
            raise ProtocolError("protocol_error")
        sequence = frame["sequence"]
        previous = state.seen.get(sequence)
        if previous is not None:
            if previous != digest:
                raise ProtocolError("protocol_error")
            return
        if sequence != state.last_sequence + 1:
            raise ProtocolError("protocol_error")
        state.seen[sequence] = digest
        state.last_sequence = sequence
        if frame["type"] == "request.cancel":
            if not state.terminal:
                state.terminal = True
                state.output_sequence += 1
                await self._send_client(
                    {
                        "type": "response.error",
                        "request_id": request_id,
                        "sequence": state.output_sequence,
                        "code": "cancelled",
                        "message": _safe_message("cancelled"),
                    }
                )
                await self._send_upstream({"type": "response.cancel", "request_id": request_id})
            return
        if not state.terminal:
            await self._send_upstream(
                {
                    "type": "response.input.delta",
                    "request_id": request_id,
                    "sequence": sequence,
                    "delta": frame["delta"],
                }
            )

    def _provider_frame(self, raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(value, dict):
            return None
        request_id = value.get("request_id")
        if not isinstance(request_id, str):
            if len(self.states) != 1:
                return None
            request_id = next(iter(self.states))
        state = self.states.get(request_id)
        if state is None or state.terminal:
            return None
        event_type = str(value.get("type") or "")
        if event_type in {"response.completed", "response.done"}:
            state.terminal = True
            out = {
                "type": "response.completed",
                "request_id": request_id,
                "sequence": state.output_sequence + 1,
                "usage": value.get("usage") or {},
            }
            state.output_sequence += 1
            return out
        if event_type in {"response.error", "error"}:
            state.terminal = True
            state.output_sequence += 1
            return {
                "type": "response.error",
                "request_id": request_id,
                "sequence": state.output_sequence,
                "code": "upstream_unavailable",
                "message": _safe_message("upstream_unavailable"),
            }
        if event_type in {"response.tool_call", "response.function_call"}:
            state.output_sequence += 1
            return {
                "type": "response.tool_call",
                "request_id": request_id,
                "sequence": state.output_sequence,
                "name": str(value.get("name") or "tool")[:1024],
                "arguments": value.get("arguments")
                if _encoded_size(value.get("arguments") or {}) <= MAX_VALUE_BYTES
                else {},
            }
        delta = value.get("delta")
        if delta is None:
            delta = value.get("text")
        if delta is None and isinstance(value.get("choices"), list):
            try:
                delta = value["choices"][0]["delta"].get("content")
            except (IndexError, KeyError, TypeError):
                delta = None
        if delta is None:
            return None
        if _encoded_size(delta) > MAX_VALUE_BYTES:
            return None
        state.output_sequence += 1
        return {"type": "response.delta", "request_id": request_id, "sequence": state.output_sequence, "delta": delta}

    async def run(self) -> None:
        async def receive_client() -> dict[str, Any]:
            if self.first_frame is not None:
                frame, self.first_frame = self.first_frame, None
                return frame
            return await asyncio.wait_for(self.ws.receive(), timeout=IDLE_TIMEOUT_SECONDS)

        try:
            while not self._closed:
                # Drain provider output without letting a slow client create an
                # unbounded task backlog.  A short wait keeps client input
                # responsive while a provider is streaming.
                try:
                    raw = await asyncio.wait_for(self.upstream.recv(), timeout=0.01)
                except asyncio.TimeoutError:
                    raw = None
                if raw is not None:
                    outgoing = self._provider_frame(raw)
                    if outgoing is not None:
                        await self._send_client(outgoing)
                active_requests = any(not state.terminal for state in self.states.values())
                receive_timeout = REQUEST_TIMEOUT_SECONDS if active_requests else IDLE_TIMEOUT_SECONDS
                data = await asyncio.wait_for(receive_client(), timeout=receive_timeout)
                try:
                    frame, digest = decode_frame(data)
                    await self._client_frame(frame, digest)
                except EOFError:
                    break
                except ProtocolError as exc:
                    code = str(exc)
                    if code == "message_too_large":
                        await self._error(None, code, close=1009)
                    else:
                        await self._error(None, "protocol_error", close=1003)
        except asyncio.TimeoutError:
            for request_id, state in self.states.items():
                if not state.terminal:
                    await self._error(request_id, "timeout")
            await self._close(1000, _safe_message("timeout"))
        except Exception as exc:
            log.warning("Codex WebSocket translation failed (%s)", type(exc).__name__)
            await self._error(None, "translation_error", close=1011)
        finally:
            await self._close(1000, "normal closure")
