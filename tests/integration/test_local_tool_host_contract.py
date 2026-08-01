"""Mock integration contract for the opt-in local MCP host boundary."""

from __future__ import annotations

import pytest
from core.policy.local_tool_host import LocalToolHost, LocalToolHostConfig, ToolAliasDenied

pytestmark = [pytest.mark.mock, pytest.mark.asyncio]


async def test_local_host_executes_only_visible_registered_aliases():
    host = LocalToolHost(
        {"mcp-git": lambda args: {"ok": args["ok"]}},
        lambda alias: alias == "mcp-git",
        config=LocalToolHostConfig(enabled=True),
    )
    result = await host.invoke("mcp-git", {"ok": True}, request_id="mock-1")
    assert result == {"ok": True}
    with pytest.raises(ToolAliasDenied):
        await host.invoke("mcp-postgres", {"ok": True}, request_id="mock-2")
