"""Fault injection integration tests using in-memory ASGI testing."""

from __future__ import annotations

import httpx
import pytest
import respx
import re
import json

pytestmark = [pytest.mark.mock, pytest.mark.asyncio]


async def test_upstream_read_timeout_returns_504(asgi_client):
    """Simulate a LiteLLM timeout and verify the gateway-engine returns 504."""
    with respx.mock(base_url="http://litellm:4000", assert_all_called=False) as respx_mock:
        respx_mock.post(re.compile(r".*/v1/chat/completions")).mock(
            side_effect=httpx.ReadTimeout("Simulated timeout")
        )

        resp = await asgi_client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Say hi."}]
            }
        )
        
        assert resp.status_code == 504
        data = resp.json()
        assert "timed out" in data.get("error", {}).get("message", "").lower()
        assert data.get("error", {}).get("type") == "timeout_error"


async def test_upstream_502_bad_gateway_surfaced(asgi_client):
    """Simulate a 502 from LiteLLM and verify the gateway-engine surfaces it."""
    with respx.mock(base_url="http://litellm:4000", assert_all_called=False) as respx_mock:
        respx_mock.post(re.compile(r".*/v1/chat/completions")).mock(
            return_value=httpx.Response(502, json={"error": "LiteLLM is down"})
        )

        resp = await asgi_client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Say hi."}]
            }
        )
        
        assert resp.status_code == 502
        data = resp.json()
        assert "LiteLLM is down" in str(data)


async def test_upstream_connection_refused_returns_502(asgi_client):
    """Simulate a connection refused error and verify the gateway-engine returns 502."""
    with respx.mock(base_url="http://litellm:4000", assert_all_called=False) as respx_mock:
        respx_mock.post(re.compile(r".*/v1/chat/completions")).mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        resp = await asgi_client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Say hi."}]
            }
        )
        
        assert resp.status_code == 502
        data = resp.json()
        assert "connection failed" in data.get("error", {}).get("message", "").lower()
        assert data.get("error", {}).get("type") == "connection_error"
