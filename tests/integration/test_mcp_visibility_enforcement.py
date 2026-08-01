"""Mock protocol fixtures for the C-RT-4 HTTP visibility seam."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.mock, pytest.mark.asyncio]

_TOKEN = "ak-echoares-core-eng-gateway-dev"


class _AllowMcpEvaluator:
    async def evaluate(self, _context):
        return {
            "gate": "allow",
            "rules_applied": ["mcp:allowlist:1"],
            "policy_version": "v1",
            "allowed_mcp_servers": ["mcp-git"],
            "denied_mcp_servers": [],
        }


@pytest.mark.parametrize(
    ("path", "payload", "auth_header"),
    [
        (
            "/v1/chat/completions",
            {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [{"type": "function", "function": {"name": "search", "mcp_server": "mcp-fetch"}}],
            },
            {"Authorization": f"Bearer {_TOKEN}"},
        ),
        (
            "/v1/responses",
            {
                "model": "gpt-4",
                "input": "hi",
                "tools": [{"type": "function", "name": "search", "mcp_server": "mcp-fetch"}],
            },
            {"Authorization": f"Bearer {_TOKEN}"},
        ),
        (
            "/v1/messages",
            {
                "model": "claude-sonnet-4-6",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 10,
                "tools": [{"name": "search", "mcp_server": "mcp-fetch", "input_schema": {"type": "object"}}],
            },
            {"x-api-key": _TOKEN},
        ),
        (
            "/v1beta/models/gemini-2.5-flash:generateContent",
            {
                "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
                "tools": [
                    {
                        "function_declarations": [
                            {
                                "name": "mcp__mcp-fetch__search",
                                "description": "search",
                                "parameters": {"type": "object"},
                            }
                        ]
                    }
                ],
            },
            {"Authorization": f"Bearer {_TOKEN}"},
        ),
    ],
)
async def test_tool_bearing_protocols_share_mcp_visibility_filter(
    asgi_client,
    mock_litellm_router,
    monkeypatch,
    path,
    payload,
    auth_header,
):
    import main as gateway_engine_main
    from api import proxy_routing

    calls = []
    original = proxy_routing.apply_mcp_visibility

    def spy(body, decision):
        calls.append((body, decision))
        return original(body, decision)

    monkeypatch.setattr(gateway_engine_main, "MCP_VISIBILITY_ENABLED", True)
    monkeypatch.setenv("MCP_VISIBILITY_ENABLED", "true")
    monkeypatch.setenv("MCP_REGISTERED_SERVERS", "mcp-git,mcp-fetch")
    monkeypatch.setattr(gateway_engine_main, "_policy_evaluator", _AllowMcpEvaluator())
    monkeypatch.setattr(proxy_routing, "apply_mcp_visibility", spy)

    response = await asgi_client.post(path, headers=auth_header, json=payload)
    assert response.status_code == 200
    assert calls, f"policy seam was not called for {path}"
    sent = mock_litellm_router.calls.last.request
    assert sent is not None
    assert "mcp-fetch" not in sent.content.decode()
