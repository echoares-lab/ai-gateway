"""Runtime tests for the opt-in Codex WebSocket translator."""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from api import codex_ws_translation as translation
from api import ws_router


class FakeWebSocket:
    def __init__(self, messages, protocols=(translation.SUBPROTOCOL,)):
        self.scope = {"subprotocols": list(protocols)}
        self.headers = {"authorization": "Bearer master-secret"}
        self.query_params = {}
        self.messages = list(messages)
        self.sent = []
        self.accept = AsyncMock()
        self.close = AsyncMock()

    async def receive(self):
        return self.messages.pop(0) if self.messages else {"type": "websocket.disconnect"}

    async def send_text(self, value):
        self.sent.append(json.loads(value))

    async def send_bytes(self, value):
        self.sent.append(json.loads(value))


class FakeUpstream:
    def __init__(self, received=()):
        self.sent = []
        self.received = list(received)
        self.ready = asyncio.Event()

    async def send(self, value):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            pass
        self.sent.append(value)
        self.ready.set()

    async def recv(self):
        if self.received:
            await self.ready.wait()
            return self.received.pop(0)
        await asyncio.sleep(1)
        return None


class FakeConnect:
    def __init__(self, upstream):
        self.upstream = upstream

    async def __aenter__(self):
        return self.upstream

    async def __aexit__(self, *_args):
        return False


def test_translation_is_disabled_by_default_and_requires_protocol(monkeypatch):
    monkeypatch.delenv("CODEX_WS_TRANSLATION_ENABLED", raising=False)
    ws = FakeWebSocket([])
    assert translation.active(ws) is False
    monkeypatch.setenv("CODEX_WS_TRANSLATION_ENABLED", "true")
    assert translation.active(ws) is True
    assert translation.active(FakeWebSocket([], protocols=())) is False


def test_decode_and_validate_enforce_contract_bounds():
    frame, digest = translation.decode_frame(
        {"text": '{"type":"request.start","request_id":"r1","model":"gpt","input":"hi"}'}
    )
    assert digest and frame["request_id"] == "r1"
    translation.validate_client_frame(frame)
    with pytest.raises(translation.ProtocolError):
        translation.decode_frame({"bytes": b"\xff"})
    with pytest.raises(translation.ProtocolError):
        translation.validate_client_frame({"type": "request.delta", "request_id": "r1", "sequence": 2})


@pytest.mark.asyncio
async def test_runtime_translates_start_and_provider_completion():
    ws = FakeWebSocket(
        [
            {"text": json.dumps({"type": "request.start", "request_id": "r1", "model": "gpt", "input": "hello"})},
            {"type": "websocket.disconnect"},
        ]
    )
    upstream = FakeUpstream(
        received=[json.dumps({"type": "response.completed", "request_id": "r1", "usage": {"total_tokens": 1}})]
    )
    translator = translation.CodexWsTranslator(ws, upstream)
    await translator.run()
    assert upstream.sent[0]["type"] == "response.create"
    assert ws.sent[0]["type"] == "response.completed"


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_does_not_echo_input():
    ws = FakeWebSocket(
        [
            {
                "text": json.dumps(
                    {"type": "request.start", "request_id": "r1", "model": "gpt", "input": "secret prompt"}
                )
            },
            {"text": json.dumps({"type": "request.cancel", "request_id": "r1", "sequence": 0})},
            {"text": json.dumps({"type": "request.cancel", "request_id": "r1", "sequence": 0})},
            {"type": "websocket.disconnect"},
        ]
    )
    upstream = FakeUpstream()
    translator = translation.CodexWsTranslator(ws, upstream)
    await translator.run()
    assert [frame["code"] for frame in ws.sent] == ["cancelled"]
    assert all("secret prompt" not in json.dumps(frame) for frame in ws.sent)


@pytest.mark.asyncio
async def test_router_keeps_direct_proxy_when_flag_off():
    ws = FakeWebSocket([{"text": "hello"}, {"type": "websocket.disconnect"}], protocols=(translation.SUBPROTOCOL,))
    upstream = FakeUpstream()
    deps = ws_router.WsRouterDeps(
        admin_redact=lambda value: ("[redacted]", bool(value)),
        build_routing_context=lambda _ws, token: {"token": token},
        evaluate_policy_engine=AsyncMock(),
        upstream_timeout=0.1,
    )
    endpoint = ws_router.create_ws_router(deps).routes[0].endpoint
    with (
        patch.dict(os.environ, {"LITELLM_MASTER_KEY": "master-secret", "CODEX_WS_TRANSLATION_ENABLED": "false"}),
        patch("api.ws_router.websockets.connect", return_value=FakeConnect(upstream)),
    ):
        await endpoint(ws)
    assert upstream.sent == ["hello"]
    ws.accept.assert_awaited_once_with(subprotocol=None)
