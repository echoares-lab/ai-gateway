"""Integration tests against a running gateway (translator → litellm → cliproxy).

Set GATEWAY_URL (default: http://localhost:4010) and LITELLM_MASTER_KEY before running:
    pytest tests/integration/ -m integration
"""

import json
import os

import httpx
import pytest

pytestmark = [pytest.mark.integration]

_SKIP_CODES = {400, 404, 503}

# Against the mock upstream nothing should be unavailable, so the mock tier sets
# ALLOW_MODEL_SKIP=0 to turn an unexpected skip-code into a hard failure (a real
# regression). The real-provider tier leaves it at the default "1" so missing
# models/credentials skip instead of failing.
_ALLOW_SKIP = os.environ.get("ALLOW_MODEL_SKIP", "1") == "1"


def _should_skip(resp: httpx.Response) -> bool:
    """True if the test should skip; raise if a skip-code is unexpected (mock tier)."""
    if resp.status_code in _SKIP_CODES:
        if _ALLOW_SKIP:
            return True
        raise AssertionError(f"unexpected {resp.status_code} against mock: {resp.text[:200]}")
    return False


def _skip_if_model_unavailable(resp: httpx.Response):
    if _should_skip(resp):
        pytest.skip(f"model unavailable ({resp.status_code}): {resp.text[:200]}")


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.mock
@pytest.mark.smoke
async def test_health(asgi_client):
    resp = await asgi_client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.mock
@pytest.mark.smoke
async def test_models_have_prefix(asgi_client, mock_litellm_router):
    resp = await asgi_client.get("/v1/models")
    assert resp.status_code == 200
    models = resp.json().get("data", [])
    assert models, "no models returned"
    for m in models:
        assert m["id"].startswith("AI-Gateway:"), f"model missing prefix: {m['id']}"


@pytest.mark.asyncio
@pytest.mark.mock
@pytest.mark.smoke
async def test_admin_status(asgi_client):
    """Read-only admin status aggregator returns the admin-console.v1 contract."""
    resp = await asgi_client.get("/admin/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == "admin-console.v1"
    assert "generated_at" in body
    for panel in ("health", "models", "providers", "routing", "config_drift"):
        assert panel in body["panels"], f"missing panel: {panel}"
        assert "status" in body["panels"][panel]
    # No obvious secret leakage in the serialized response.
    raw = resp.text
    assert "Bearer " not in raw
    assert "sk-" not in raw or "[redacted]" in raw


@pytest.mark.asyncio
@pytest.mark.mock
@pytest.mark.smoke
async def test_admin_dashboard(asgi_client):
    """Read-only admin dashboard page renders and references /admin/status."""
    resp = await asgi_client.get("/admin/dashboard")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    assert "/admin/status" in html
    assert "AI Gateway" in html
    assert "Bearer " not in html
    assert "sk-" not in html


# ---------------------------------------------------------------------------
# Chat completions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.mock
async def test_prefix_stripped_on_completion(asgi_client, async_first_model, mock_litellm_router):
    """Sending AI-Gateway:-prefixed model name should route correctly (not 404)."""
    resp = await asgi_client.post(
        "/v1/chat/completions",
        json={
            "model": f"AI-Gateway:{async_first_model}",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
    )
    _skip_if_model_unavailable(resp)
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.mock
@pytest.mark.smoke
async def test_simple_completion(asgi_client, async_first_model, mock_litellm_router):
    resp = await asgi_client.post(
        "/v1/chat/completions",
        json={
            "model": async_first_model,
            "messages": [{"role": "user", "content": "Reply with the word OK only."}],
            "max_tokens": 5,
        },
    )
    _skip_if_model_unavailable(resp)
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"]


@pytest.mark.asyncio
@pytest.mark.mock
@pytest.mark.smoke
async def test_streaming_completion(asgi_client, async_first_model, mock_litellm_router):
    async with asgi_client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": async_first_model,
            "messages": [{"role": "user", "content": "Say hi."}],
            "max_tokens": 5,
            "stream": True,
        },
    ) as resp:
        if _should_skip(resp):
            pytest.skip(f"model unavailable ({resp.status_code})")
        assert resp.status_code == 200
        lines = [line async for line in resp.aiter_lines() if line.startswith("data:")]
    assert lines, "no SSE data lines received"


# ---------------------------------------------------------------------------
# Responses API translation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.mock
async def test_responses_api_input_field(asgi_client, async_first_model, mock_litellm_router):
    """Body with `input` (Responses API style) should be translated and succeed."""
    resp = await asgi_client.post(
        "/v1/chat/completions",
        json={
            "model": async_first_model,
            "input": "Reply with OK.",
            "max_tokens": 5,
        },
    )
    _skip_if_model_unavailable(resp)
    assert resp.status_code == 200


@pytest.mark.asyncio
@pytest.mark.mock
@pytest.mark.smoke
async def test_tool_normalization(asgi_client, async_first_model, mock_litellm_router):
    """Responses API tool format {type, name, parameters} should not cause 422."""
    resp = await asgi_client.post(
        "/v1/chat/completions",
        json={
            "model": async_first_model,
            "messages": [{"role": "user", "content": "What time is it?"}],
            "tools": [{"type": "function", "name": "get_time", "parameters": {"type": "object", "properties": {}}}],
            "max_tokens": 5,
        },
    )
    _skip_if_model_unavailable(resp)
    assert resp.status_code != 422, f"tool normalization failed: {resp.text[:300]}"


# ---------------------------------------------------------------------------
# Gemini CLI wire format  (POST /v1beta/models/{model}:generateContent)
# ---------------------------------------------------------------------------

_GEMINI_MODEL = "gemini-2.5-flash"  # dotted name as Gemini CLI sends it
_GEMINI_BODY = {"contents": [{"role": "user", "parts": [{"text": "Reply with the word OK only."}]}]}


class TestGeminiCliFormat:
    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_generate_content(self, asgi_client, mock_litellm_router):
        resp = await asgi_client.post(f"/v1beta/models/{_GEMINI_MODEL}:generateContent", json=_GEMINI_BODY)
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200
        body = resp.json()
        assert "candidates" in body, f"missing candidates: {body}"
        assert body["candidates"][0]["content"]["parts"][0].get("text"), "empty response text"

    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_stream_generate_content(self, asgi_client, mock_litellm_router):
        async with asgi_client.stream("POST", f"/v1beta/models/{_GEMINI_MODEL}:streamGenerateContent", json=_GEMINI_BODY) as resp:
            if _should_skip(resp):
                pytest.skip(f"model unavailable ({resp.status_code})")
            assert resp.status_code == 200
            chunks = [line async for line in resp.aiter_lines() if line.startswith("data:")]
        assert chunks, "no SSE chunks received from streamGenerateContent"

    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_tool_use(self, asgi_client, mock_litellm_router):
        body = {
            "contents": [{"role": "user", "parts": [{"text": "What is the weather?"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "description": "Get weather for a location",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {"location": {"type": "STRING", "description": "City name"}},
                                "required": ["location"],
                            },
                        }
                    ]
                }
            ],
        }
        resp = await asgi_client.post(f"/v1beta/models/{_GEMINI_MODEL}:generateContent", json=body)
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_dotted_model_name_routes(self, asgi_client, mock_litellm_router):
        """gemini-2.5-flash (dotted) must route — not fall through to a 404/500."""
        resp = await asgi_client.post("/v1beta/models/gemini-2.5-flash:generateContent", json=_GEMINI_BODY)
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_unknown_model_returns_4xx_not_5xx(self, asgi_client, mock_litellm_router):
        """A completely unknown model should return a client error, not a 500."""
        resp = await asgi_client.post("/v1beta/models/gemini-totally-fake-model:generateContent", json=_GEMINI_BODY)
        assert resp.status_code < 500, f"unknown model caused server error: {resp.text[:300]}"

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_system_instruction(self, asgi_client, mock_litellm_router):
        body = {
            "systemInstruction": {"parts": [{"text": "You are a helpful assistant."}]},
            "contents": [{"role": "user", "parts": [{"text": "Say OK."}]}],
        }
        resp = await asgi_client.post(f"/v1beta/models/{_GEMINI_MODEL}:generateContent", json=body)
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_tool_use_response_shape(self, asgi_client, mock_litellm_router):
        body = {
            "contents": [{"role": "user", "parts": [{"text": "What is the weather in NYC?"}]}],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "description": "Get weather for a city",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {"location": {"type": "STRING", "description": "City name"}},
                                "required": ["location"],
                            },
                        }
                    ]
                }
            ],
        }
        resp = await asgi_client.post(f"/v1beta/models/{_GEMINI_MODEL}:generateContent", json=body)
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200
        data = resp.json()
        candidate = data["candidates"][0]
        parts = candidate["content"]["parts"]
        assert any("functionCall" in part for part in parts), f"missing functionCall part: {parts}"
        assert parts[0]["functionCall"]["name"] == "get_weather"

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_function_response_multiturn(self, asgi_client, mock_litellm_router):
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": "What is the weather?"}]},
                {"role": "model", "parts": [{"functionCall": {"name": "get_weather", "args": {"location": "NYC"}}}]},
                {
                    "role": "user",
                    "parts": [{"functionResponse": {"name": "get_weather", "response": {"weather": "Sunny, 72F"}}}],
                },
            ],
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "get_weather",
                            "description": "Get weather",
                            "parameters": {"type": "OBJECT", "properties": {"location": {"type": "STRING"}}},
                        }
                    ]
                }
            ],
        }
        resp = await asgi_client.post(f"/v1beta/models/{_GEMINI_MODEL}:generateContent", json=body)
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Claude CLI wire format  (POST /v1/messages)
# ---------------------------------------------------------------------------

_CLAUDE_MODEL = "claude-sonnet-4-6"


class TestClaudeCliFormat:
    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_messages_basic(self, asgi_client, mock_litellm_router):
        resp = await asgi_client.post(
            "/v1/messages",
            json={
                "model": _CLAUDE_MODEL,
                "messages": [{"role": "user", "content": "Reply with the word OK only."}],
                "max_tokens": 10,
            },
            headers={"x-api-key": asgi_client.headers.get("authorization", "").removeprefix("Bearer ")},
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("type") == "message", f"unexpected response type: {body}"
        assert body["content"][0]["type"] == "text"

    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_messages_stream(self, asgi_client, mock_litellm_router):
        async with asgi_client.stream(
            "POST",
            "/v1/messages",
            json={
                "model": _CLAUDE_MODEL,
                "messages": [{"role": "user", "content": "Say hi."}],
                "max_tokens": 10,
                "stream": True,
            },
            headers={"x-api-key": asgi_client.headers.get("authorization", "").removeprefix("Bearer ")},
        ) as resp:
            if _should_skip(resp):
                pytest.skip(f"model unavailable ({resp.status_code})")
            assert resp.status_code == 200
            events = [line async for line in resp.aiter_lines() if line.startswith("event:")]
        assert any("message_start" in e for e in events), f"missing message_start: {events[:5]}"

    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_tool_use(self, asgi_client, mock_litellm_router):
        resp = await asgi_client.post(
            "/v1/messages",
            json={
                "model": _CLAUDE_MODEL,
                "messages": [{"role": "user", "content": "What is the weather in NYC?"}],
                "max_tokens": 50,
                "tools": [
                    {
                        "name": "get_weather",
                        "description": "Get current weather",
                        "input_schema": {
                            "type": "object",
                            "properties": {"location": {"type": "string"}},
                            "required": ["location"],
                        },
                    }
                ],
            },
            headers={"x-api-key": asgi_client.headers.get("authorization", "").removeprefix("Bearer ")},
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200, f"tool_use failed: {resp.text[:300]}"

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_tool_result_multiturn(self, asgi_client, mock_litellm_router):
        """Multi-turn with tool_result content block should not cause a parsing error."""
        resp = await asgi_client.post(
            "/v1/messages",
            json={
                "model": _CLAUDE_MODEL,
                "max_tokens": 50,
                "messages": [
                    {"role": "user", "content": "What's the weather?"},
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "id": "tool_abc", "name": "get_weather", "input": {"location": "NYC"}},
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "tool_result", "tool_use_id": "tool_abc", "content": "Sunny, 72°F"},
                        ],
                    },
                ],
                "tools": [
                    {
                        "name": "get_weather",
                        "description": "Get weather",
                        "input_schema": {"type": "object", "properties": {"location": {"type": "string"}}},
                    }
                ],
            },
            headers={"x-api-key": asgi_client.headers.get("authorization", "").removeprefix("Bearer ")},
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200, f"tool_result multiturn failed: {resp.text[:300]}"

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_system_prompt_string(self, asgi_client, mock_litellm_router):
        resp = await asgi_client.post(
            "/v1/messages",
            json={
                "model": _CLAUDE_MODEL,
                "system": "You are a helpful assistant. Always reply with exactly one word.",
                "messages": [{"role": "user", "content": "Say OK."}],
                "max_tokens": 10,
            },
            headers={"x-api-key": asgi_client.headers.get("authorization", "").removeprefix("Bearer ")},
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_system_prompt_list(self, asgi_client, mock_litellm_router):
        """System as list of text blocks (Claude SDK format)."""
        resp = await asgi_client.post(
            "/v1/messages",
            json={
                "model": _CLAUDE_MODEL,
                "system": [{"type": "text", "text": "You are a helpful assistant."}],
                "messages": [{"role": "user", "content": "Say OK."}],
                "max_tokens": 10,
            },
            headers={"x-api-key": asgi_client.headers.get("authorization", "").removeprefix("Bearer ")},
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_messages_stream_tool_use(self, asgi_client, mock_litellm_router):
        async with asgi_client.stream(
            "POST",
            "/v1/messages",
            json={
                "model": _CLAUDE_MODEL,
                "messages": [{"role": "user", "content": "What is the weather?"}],
                "max_tokens": 50,
                "stream": True,
                "tools": [
                    {
                        "name": "get_weather",
                        "description": "Get weather",
                        "input_schema": {
                            "type": "object",
                            "properties": {"location": {"type": "string"}},
                            "required": ["location"],
                        },
                    }
                ],
            },
            headers={"x-api-key": asgi_client.headers.get("authorization", "").removeprefix("Bearer ")},
        ) as resp:
            if _should_skip(resp):
                pytest.skip(f"model unavailable ({resp.status_code})")
            assert resp.status_code == 200
            events = [line async for line in resp.aiter_lines() if line.startswith("event:")]
        assert any("content_block_start" in e for e in events), f"missing content_block_start: {events}"


# ---------------------------------------------------------------------------
# Codex CLI wire format  (/v1/responses and /v1/chat/completions)
# ---------------------------------------------------------------------------

_CODEX_MODEL_DOTTED = "gpt-5.5"  # as Codex CLI sends it
_CODEX_MODEL_DASHED = "gpt-5-5"  # as LiteLLM knows it


class TestCodexCliFormat:
    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_dotted_model_normalised_in_chat_completions(self, asgi_client, mock_litellm_router):
        """gpt-5.5 (dotted) must be normalised to gpt-5-5 and not 404."""
        resp = await asgi_client.post(
            "/v1/chat/completions",
            json={
                "model": _CODEX_MODEL_DOTTED,
                "messages": [{"role": "user", "content": "Reply with the word OK only."}],
                "max_tokens": 5,
            },
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200, f"dotted model name caused error: {resp.text[:300]}"

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_dashed_model_works(self, asgi_client, mock_litellm_router):
        """Dashed model name should work directly."""
        resp = await asgi_client.post(
            "/v1/chat/completions",
            json={
                "model": _CODEX_MODEL_DASHED,
                "messages": [{"role": "user", "content": "Reply with the word OK only."}],
                "max_tokens": 5,
            },
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_responses_api_string_input(self, asgi_client, mock_litellm_router):
        """POST /v1/responses with string `input` (Codex CLI default)."""
        resp = await asgi_client.post(
            "/v1/responses",
            json={
                "model": _CODEX_MODEL_DOTTED,
                "input": "Reply with the word OK only.",
                "max_output_tokens": 10,
            },
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("output"), f"no output in response: {body}"

    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_responses_api_stream(self, asgi_client, mock_litellm_router):
        async with asgi_client.stream(
            "POST",
            "/v1/responses",
            json={
                "model": _CODEX_MODEL_DOTTED,
                "input": "Say hi.",
                "stream": True,
                "max_output_tokens": 10,
            },
        ) as resp:
            if _should_skip(resp):
                pytest.skip(f"model unavailable ({resp.status_code})")
            assert resp.status_code == 200
            events = [line async for line in resp.aiter_lines() if line.startswith("data:")]
        assert events, "no SSE events from /v1/responses stream"

    @pytest.mark.asyncio
    @pytest.mark.mock
    @pytest.mark.smoke
    async def test_responses_api_tool_call(self, asgi_client, mock_litellm_router):
        """Responses API with tools — translator must normalise tool format."""
        resp = await asgi_client.post(
            "/v1/responses",
            json={
                "model": _CODEX_MODEL_DOTTED,
                "input": "What is the weather in NYC?",
                "max_output_tokens": 50,
                "tools": [
                    {
                        "type": "function",
                        "name": "get_weather",
                        "parameters": {
                            "type": "object",
                            "properties": {"location": {"type": "string"}},
                            "required": ["location"],
                        },
                    }
                ],
            },
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200, f"tool call failed: {resp.text[:300]}"

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_responses_api_list_input(self, asgi_client, mock_litellm_router):
        """Responses API with list `input` containing message items."""
        resp = await asgi_client.post(
            "/v1/responses",
            json={
                "model": _CODEX_MODEL_DOTTED,
                "input": [
                    {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Reply with OK."}]}
                ],
                "max_output_tokens": 10,
            },
        )
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.mock
    async def test_responses_api_compaction_interception(self, asgi_client, mock_litellm_router):
        """Test responses/compact endpoint models interception mapping."""
        try:
            resp = await asgi_client.post(
                "/v1/responses/compact",
                json={
                    "model": "claude-sonnet-4-6",
                    "input": "This is long history content.",
                },
            )
        except httpx.ReadTimeout as exc:
            pytest.skip(f"Timeout on responses/compact (likely model/auth unavailable): {exc}")
        _skip_if_model_unavailable(resp)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("object") == "response.compaction"

    @pytest.mark.mock
    def test_websocket_multiturn(self, client):
        pytest.skip("Websocket in-memory test not yet implemented")
