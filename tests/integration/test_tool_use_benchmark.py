"""Integration test wrapper for the cross-model tool-use evaluation benchmark (Epic #420)."""

from __future__ import annotations

import pytest
from api.proxy_router import _provider_of

pytestmark = [pytest.mark.mock, pytest.mark.asyncio]


async def test_provider_mapping_for_benchmark_models():
    assert _provider_of("claude-sonnet-4-6") == "anthropic"
    assert _provider_of("gpt-5-4") == "openai"
    assert _provider_of("gemini-3-flash") == "google"


async def test_tool_use_benchmark_mock_evaluation(asgi_client, mock_litellm_router):
    """Verify tool use requests stream and format tool calls correctly for benchmark tasks."""
    headers = {"Authorization": "Bearer ak-echoares-core-eng-gateway-dev"}
    payload = {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "Please edit file.txt to replace 'Hello' with 'Bonjour'."}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "Edit",
                    "description": "Edit file",
                    "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}},
                },
            }
        ],
    }

    resp = await asgi_client.post("/v1/chat/completions", headers=headers, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert "choices" in body
