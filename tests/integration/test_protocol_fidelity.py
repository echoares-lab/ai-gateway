"""Protocol-level integration and fidelity tests for Claude and Cursor (Epic #420)."""

from __future__ import annotations

import json
import pytest
import httpx
from conftest import MASTER_KEY

pytestmark = [pytest.mark.mock, pytest.mark.asyncio]

_TENANT_KEY = "ak-echoares-core-eng-gateway-dev"
_DEFAULT_HEADERS = {"Authorization": f"Bearer {_TENANT_KEY}"}


async def test_cursor_protocol_header_injection(asgi_client, mock_litellm_router):
    """Verify that User-Agent containing Cursor triggers header injection."""
    resp = await asgi_client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {_TENANT_KEY}",
            "User-Agent": "Cursor/0.45.0 (composer)",
        },
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )
    assert resp.status_code == 200
    # The ASGI mock router captures headers sent to LiteLLM.
    # Since mock_litellm_router is intercepted by respx, let's verify if x-gateway-client was sent.
    last_request = mock_litellm_router.calls.last.request
    assert last_request.headers.get("x-gateway-client") == "cursor"


async def test_x_force_model_header_override(asgi_client, mock_litellm_router, monkeypatch):
    """Verify that the X-Force-Model header overrides target model routing."""
    monkeypatch.setenv("ALLOW_DEV_MODEL_FORCE", "true")
    
    resp = await asgi_client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {_TENANT_KEY}",
            "X-Force-Model": "claude-sonnet-4-6",
        },
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "ping"}],
        },
    )
    assert resp.status_code == 200
    
    last_request = mock_litellm_router.calls.last.request
    sent_body = json.loads(last_request.read())
    assert sent_body["model"] == "claude-sonnet-4-6"


async def test_claude_protocol_system_prompt_normalization(asgi_client, mock_litellm_router):
    """Verify that Anthropic messages API system prompt lists normalize to OpenAI format."""
    resp = await asgi_client.post(
        "/v1/messages",
        headers={
            "x-api-key": _TENANT_KEY,
        },
        json={
            "model": "claude-sonnet-4-6",
            "system": [
                {"type": "text", "text": "You are a specialized translator."}
            ],
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 10,
        },
    )
    assert resp.status_code == 200
    
    last_request = mock_litellm_router.calls.last.request
    sent_body = json.loads(last_request.read())
    
    # Verify OpenAI payload has system message at the beginning
    assert sent_body["messages"][0]["role"] == "system"
    assert sent_body["messages"][0]["content"] == "You are a specialized translator."
