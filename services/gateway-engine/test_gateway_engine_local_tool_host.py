"""Unit tests for the isolated local MCP tool-host boundary (#607)."""

from __future__ import annotations

import asyncio

import pytest
from core.policy.local_tool_host import (
    MAX_REQUEST_BYTES,
    LocalToolHost,
    LocalToolHostConfig,
    ToolAliasDenied,
    ToolBoundsExceeded,
    ToolHostDisabled,
    ToolTimedOut,
)


@pytest.fixture(autouse=True)
def _non_root_test_runtime(monkeypatch):
    monkeypatch.setattr("core.policy.local_tool_host.os.geteuid", lambda: 1001)


def _host(handler, *, config=None, traces=None, visible=True):
    return LocalToolHost(
        {"mcp-git": handler},
        lambda alias: visible and alias == "mcp-git",
        config=config or LocalToolHostConfig(enabled=True),
        trace=(lambda **event: traces.append(event) if traces is not None else None),
    )


def test_config_cannot_raise_contract_bounds():
    with pytest.raises(ValueError):
        LocalToolHostConfig(enabled=True, timeout_seconds=11)
    with pytest.raises(ValueError):
        LocalToolHostConfig(enabled=True, max_request_bytes=MAX_REQUEST_BYTES + 1)


@pytest.mark.asyncio
async def test_disabled_host_rolls_back_without_calling_handler():
    called = False

    async def handler(_args):
        nonlocal called
        called = True

    host = _host(handler, config=LocalToolHostConfig(enabled=False))
    with pytest.raises(ToolHostDisabled):
        await host.invoke("mcp-git", {})
    assert called is False


@pytest.mark.asyncio
async def test_alias_visibility_and_sandbox_flags_are_enforced():
    host = _host(lambda args: args)
    with pytest.raises(ToolAliasDenied):
        await host.invoke("mcp-postgres", {})
    with pytest.raises(ToolAliasDenied):
        await host.invoke("../mcp-git", {})
    with pytest.raises(ToolAliasDenied):
        await _host(lambda args: args, visible=False).invoke("mcp-git", {})
    with pytest.raises(ToolAliasDenied):
        await _host(lambda args: args, config=LocalToolHostConfig(enabled=True, read_only=False)).invoke("mcp-git", {})
    with pytest.raises(ToolAliasDenied):
        await _host(lambda args: args, config=LocalToolHostConfig(enabled=True, network_enabled=True)).invoke(
            "mcp-git", {}
        )


@pytest.mark.asyncio
async def test_root_runtime_is_rejected(monkeypatch):
    monkeypatch.setattr("core.policy.local_tool_host.os.geteuid", lambda: 0)
    with pytest.raises(ToolAliasDenied):
        await _host(lambda args: args).invoke("mcp-git", {})


@pytest.mark.asyncio
async def test_success_is_bounded_and_trace_contains_no_arguments_or_secrets():
    traces = []

    async def handler(args):
        return {"ok": True, "echo": args["value"]}

    result = await _host(handler, traces=traces).invoke(
        "mcp-git",
        {"value": "private", "authorization": "secret"},
        request_id="req-1",
    )
    assert result == {"ok": True, "echo": "private"}
    assert traces and traces[0]["alias"] == "mcp-git"
    assert set(traces[0]) == {"request_id", "alias", "duration_ms", "outcome", "size"}
    assert "private" not in str(traces[0])
    assert "secret" not in str(traces[0])


@pytest.mark.asyncio
async def test_request_response_size_and_depth_bounds():
    config = LocalToolHostConfig(enabled=True, max_request_bytes=8, max_json_depth=2)
    with pytest.raises(ToolBoundsExceeded):
        await _host(lambda args: args, config=config).invoke("mcp-git", {"value": "too large"})

    config = LocalToolHostConfig(enabled=True, max_json_depth=2)
    with pytest.raises(ToolBoundsExceeded):
        await _host(lambda _args: {"a": {"b": {"c": 1}}}, config=config).invoke("mcp-git", {})

    config = LocalToolHostConfig(enabled=True, max_response_bytes=4)
    with pytest.raises(ToolBoundsExceeded):
        await _host(lambda _args: {"result": "long"}, config=config).invoke("mcp-git", {})


@pytest.mark.asyncio
async def test_timeout_and_cancellation_propagate_without_retries():
    calls = 0

    async def slow(_args):
        nonlocal calls
        calls += 1
        await asyncio.sleep(1)

    config = LocalToolHostConfig(enabled=True, timeout_seconds=0.001)
    with pytest.raises(ToolTimedOut):
        await _host(slow, config=config).invoke("mcp-git", {})
    assert calls == 1

    task = asyncio.create_task(_host(slow).invoke("mcp-git", {}))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == 2
