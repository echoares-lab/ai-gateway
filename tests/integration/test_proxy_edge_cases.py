"""Client and response edge-case contracts for the catch-all proxy."""

from __future__ import annotations

import json
import re

import httpx
import pytest
import respx

pytestmark = [pytest.mark.mock, pytest.mark.asyncio]


async def test_malformed_client_json_is_forwarded_without_gateway_500(asgi_client):
    """Malformed payloads produce the upstream contract, not an internal gateway error."""
    with respx.mock(base_url="http://litellm:4000", assert_all_called=False) as router:
        route = router.post(re.compile(r".*/v1/chat/completions")).mock(
            return_value=httpx.Response(400, content=b"invalid request", headers={"content-type": "text/plain"})
        )

        resp = await asgi_client.post(
            "/v1/chat/completions", content=b'{"model":', headers={"content-type": "application/json"}
        )

        assert route.called
        assert route.calls[0].request.content == b'{"model":'
        assert resp.status_code == 400
        assert resp.content == b"invalid request"
        assert resp.headers["content-type"].startswith("text/plain")


async def test_missing_model_preserves_upstream_validation_contract(asgi_client):
    """A request without model remains an upstream validation response."""
    with respx.mock(base_url="http://litellm:4000", assert_all_called=False) as router:
        route = router.post(re.compile(r".*/v1/chat/completions")).mock(
            return_value=httpx.Response(400, json={"error": {"message": "model is required"}})
        )

        resp = await asgi_client.post("/v1/chat/completions", json={"messages": []})

        assert route.called
        forwarded = json.loads(route.calls[0].request.content)
        assert "model" not in forwarded
        assert resp.status_code == 400
        assert resp.json()["error"]["message"] == "model is required"


async def test_empty_upstream_body_is_returned_unchanged(asgi_client):
    """An empty successful upstream response does not get synthesized into JSON."""
    with respx.mock(base_url="http://litellm:4000", assert_all_called=False) as router:
        router.post(re.compile(r".*/v1/chat/completions")).mock(return_value=httpx.Response(204, content=b""))

        resp = await asgi_client.post(
            "/v1/chat/completions", json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]}
        )

        assert resp.status_code == 204
        assert resp.content == b""


async def test_upstream_json_content_type_and_body_are_preserved(asgi_client):
    """Successful JSON responses retain their wire format through the catch-all route."""
    payload = b'{"id":"completion-1","choices":[]}'
    with respx.mock(base_url="http://litellm:4000", assert_all_called=False) as router:
        router.post(re.compile(r".*/v1/chat/completions")).mock(
            return_value=httpx.Response(200, content=payload, headers={"content-type": "application/json"})
        )

        resp = await asgi_client.post(
            "/v1/chat/completions", json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]}
        )

        assert resp.status_code == 200
        assert resp.content == payload
        assert resp.headers["content-type"].startswith("application/json")
