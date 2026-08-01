"""C-RT-3 WebSocket parity helpers and opt-in behavior tests."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from api import ws_router


def test_first_frame_model_parser_is_bounded_and_protocol_agnostic():
    assert ws_router._ws_model_from_frame({"text": '{"model":"gpt-5-4"}'}) == "gpt-5-4"
    assert ws_router._ws_model_from_frame({"text": '{"model":""}'}) is None
    assert ws_router._ws_model_from_frame({"bytes": b'{"model":"claude-sonnet-4-6"}'}) == "claude-sonnet-4-6"
    assert ws_router._ws_model_from_frame({"text": "x" * (ws_router.WS_FIRST_FRAME_MAX_BYTES + 1)}) is None
    assert (
        ws_router._ws_model_from_frame({"text": '{"model":"gpt-5-4", "authorization":"Bearer sk-secret"}'}) == "gpt-5-4"
    )


def test_ws_policy_denial_reason_redacts_credentials_and_bounds_safe_reasons():
    assert (
        ws_router._ws_policy_denial_reason({"gate": "deny", "deny_reason": "workspace blocked"}) == "workspace blocked"
    )
    assert ws_router._ws_policy_denial_reason({"gate": "deny", "deny_reason": "Bearer sk-secret"}) == "Policy denied"
    assert ws_router._ws_policy_denial_reason({"gate": "deny", "deny_reason": "x" * 200}) == "x" * 123


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    (
        asyncio.TimeoutError(),
        RuntimeError("Bearer sk-secret"),
    ),
)
async def test_ws_policy_failures_roll_back_to_direct_proxy(failure):
    evaluate = AsyncMock(side_effect=failure)
    assert await ws_router._evaluate_ws_policy(evaluate, {"requested_model": "gpt-5-4"}) is None


@pytest.mark.asyncio
async def test_ws_policy_malformed_decision_rolls_back_to_direct_proxy():
    evaluate = AsyncMock(return_value={"gate": "unexpected", "session_key": "secret"})
    assert await ws_router._evaluate_ws_policy(evaluate, {"requested_model": "gpt-5-4"}) is None


@pytest.mark.asyncio
async def test_opt_in_first_frame_evaluates_model_and_forwards_same_frame():
    class FakeWebSocket:
        headers = {"authorization": "Bearer master-secret"}
        query_params = {}

        def __init__(self):
            self.accept = AsyncMock()
            self.close = AsyncMock()
            self.sent = []
            self._messages = [{"text": '{"model":"gpt-5-4","input":"hello"}'}, {"type": "websocket.disconnect"}]

        async def receive(self):
            return self._messages.pop(0)

        async def send_text(self, value):
            self.sent.append(value)

        async def send_bytes(self, value):
            self.sent.append(value)

    class FakeUpstream:
        def __init__(self):
            self.sent = []

        async def send(self, value):
            self.sent.append(value)

        async def recv(self):
            await asyncio.sleep(0)
            raise asyncio.CancelledError

    class FakeConnect:
        def __init__(self, upstream):
            self.upstream = upstream

        async def __aenter__(self):
            return self.upstream

        async def __aexit__(self, *exc):
            return False

    ws = FakeWebSocket()
    upstream = FakeUpstream()
    evaluate = AsyncMock(return_value={"gate": "allow", "session_key": "sess-1"})
    deps = ws_router.WsRouterDeps(
        admin_redact=lambda value: ("[redacted]", True),
        build_routing_context=lambda _ws, token: {"requested_model": "codex", "token": token},
        evaluate_policy_engine=evaluate,
        upstream_timeout=0.1,
    )
    router = ws_router.create_ws_router(deps)
    endpoint = router.routes[0].endpoint

    with (
        patch.dict(
            os.environ,
            {
                "LITELLM_MASTER_KEY": "master-secret",
                "POLICY_ENGINE_ENABLED": "true",
                "POLICY_ENGINE_WS_EVALUATE": "true",
            },
            clear=False,
        ),
        patch("api.ws_router.websockets.connect", return_value=FakeConnect(upstream)),
    ):
        await endpoint(ws)

    assert evaluate.await_count == 1
    assert evaluate.await_args.args[0]["requested_model"] == "gpt-5-4"
    assert upstream.sent == ['{"model":"gpt-5-4","input":"hello"}']


@pytest.mark.asyncio
async def test_opt_in_first_frame_deny_closes_without_upstream_connection():
    class FakeWebSocket:
        headers = {"authorization": "Bearer master-secret"}
        query_params = {}

        def __init__(self):
            self.accept = AsyncMock()
            self.close = AsyncMock()

        async def receive(self):
            return {"text": '{"model":"gpt-5-4"}'}

    ws = FakeWebSocket()
    evaluate = AsyncMock(return_value={"gate": "deny", "deny_reason": "Bearer sk-secret"})
    deps = ws_router.WsRouterDeps(
        admin_redact=lambda value: ("[redacted]", True),
        build_routing_context=lambda _ws, token: {"requested_model": "codex", "token": token},
        evaluate_policy_engine=evaluate,
        upstream_timeout=0.1,
    )
    endpoint = ws_router.create_ws_router(deps).routes[0].endpoint

    with (
        patch.dict(
            os.environ,
            {
                "LITELLM_MASTER_KEY": "master-secret",
                "POLICY_ENGINE_ENABLED": "true",
                "POLICY_ENGINE_WS_EVALUATE": "true",
            },
            clear=False,
        ),
        patch("api.ws_router.websockets.connect") as connect,
    ):
        await endpoint(ws)

    ws.close.assert_awaited_once_with(code=1008, reason="Policy denied")
    connect.assert_not_called()
