import re
import os
import pytest
import pytest_asyncio
import httpx
import respx
import json
from dotenv import load_dotenv

import fakeredis.aioredis
from httpx import ASGITransport

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/gateway-engine')))

# Set env vars BEFORE importing main
os.environ['POLICY_MOCK_SCENARIOS'] = '1'
os.environ['POLICY_ENGINE_ENABLED'] = '1'
os.environ['CACHE_ENABLED'] = '1'
os.environ['LITELLM_URL'] = 'http://litellm:4000'

import main as gateway_engine_main
from main import app

load_dotenv()

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4010")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")


@pytest.fixture(scope="session")
def client():
    headers = {"Authorization": f"Bearer {MASTER_KEY}"} if MASTER_KEY else {}
    with httpx.Client(base_url=GATEWAY_URL, headers=headers, timeout=30) as c:
        yield c


@pytest_asyncio.fixture
async def asgi_client(monkeypatch):
    """Provides an httpx.AsyncClient hooked directly to the Gateway Engine ASGI app, bypassing network."""
    
    # Setup fakeredis for the gateway-engine
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(gateway_engine_main, "_redis", fake_redis)
    
    # Initialize globals normally set in _lifespan
    gateway_engine_main._client = httpx.AsyncClient()
    gateway_engine_main.LITELLM = "http://litellm:4000"
    gateway_engine_main._policy_evaluator = gateway_engine_main.PolicyEvaluator.from_env()
    
    headers = {"Authorization": f"Bearer {MASTER_KEY}"} if MASTER_KEY else {}
    async with ASGITransport(app=app) as transport:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", headers=headers
        ) as c:
            yield c
    
    await gateway_engine_main._client.aclose()


@pytest_asyncio.fixture
async def async_first_model(asgi_client, mock_litellm_router):
    """Return the first available model ID (without AI-Gateway: prefix) using asgi_client."""
    resp = await asgi_client.get("/v1/models")
    resp.raise_for_status()
    models = resp.json().get("data", [])
    if not models:
        pytest.skip("no models available")
    raw = models[0]["id"]
    return raw.removeprefix("AI-Gateway:")


# --- LiteLLM respx mocks ---
LITELLM_URL = "http://litellm:4000"

@pytest.fixture
def mock_litellm_router():
    """Provides a base respx router mocking common LiteLLM endpoints.
    Can be overridden by individual tests."""
    with respx.mock(base_url=LITELLM_URL, assert_all_called=False) as router:
        router.get("/health/readiness").mock(return_value=httpx.Response(200, json={"status": "healthy"}))
        router.get("/health").mock(return_value=httpx.Response(200, json={"status": "healthy"}))
        
        router.get("/v1/models").mock(return_value=httpx.Response(200, json={
            "data": [
                {"id": "gpt-4", "object": "model", "created": 123456789, "owned_by": "openai"},
                {"id": "claude-sonnet-4-6", "object": "model", "created": 123456789, "owned_by": "anthropic"},
                {"id": "gemini-2.5-flash", "object": "model", "created": 123456789, "owned_by": "google"}
            ]
        }))

        router.post("/v1/responses/compact").mock(return_value=httpx.Response(200, json={
            "object": "response.compaction",
            "output": "compacted response"
        }))
        
        def _chat_completion_mock(request):
            try:
                body = json.loads(request.content)
                agent_id = body.get("metadata", {}).get("agent_id")
                if agent_id == "test:seed-429-counter":
                    return httpx.Response(429, json={"error": "too many requests"})
                
                streaming = body.get("stream", False)
                tools = body.get("tools")
                
                if streaming:
                    # Return SSE stream
                    sse_content = (
                        'data: {"choices": [{"delta": {"role": "assistant", "content": "mocked "}, "index": 0, "finish_reason": null}]}\n\n'
                        'data: {"choices": [{"delta": {"content": "stream"}, "index": 0, "finish_reason": "stop"}]}\n\n'
                        'data: [DONE]\n\n'
                    )
                    return httpx.Response(200, content=sse_content, headers={"content-type": "text/event-stream"})

                if tools:
                    # Return tool call response
                    return httpx.Response(200, json={
                        "id": "chatcmpl-mock-tools",
                        "object": "chat.completion",
                        "created": 123456789,
                        "model": "gpt-4",
                        "choices": [{
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [{
                                    "id": "call_123",
                                    "type": "function",
                                    "function": {"name": "get_weather", "arguments": '{"location": "NYC"}'}
                                }]
                            },
                            "finish_reason": "tool_calls"
                        }],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
                    })

            except Exception as e:
                print(f"DEBUG: _chat_completion_mock error: {e}")
                pass

            return httpx.Response(200, json={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 123456789,
                "model": "gpt-4",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "mocked response"},
                    "finish_reason": "stop"
                }],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
            })

        router.post(re.compile(r".*/v1/chat/completions")).mock(side_effect=_chat_completion_mock)
        
        yield router
