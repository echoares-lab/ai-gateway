import re

import importlib
import os
import pytest
import pytest_asyncio
import httpx
import respx
import fakeredis.aioredis
from httpx import ASGITransport
from dotenv import load_dotenv

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/translator')))

# Set env vars BEFORE importing main
os.environ['POLICY_MOCK_SCENARIOS'] = '1'
os.environ['POLICY_ENGINE_ENABLED'] = '1'
os.environ['CACHE_ENABLED'] = '1'

import main as translator_main
from main import app


os.environ['POLICY_MOCK_SCENARIOS'] = '1'
os.environ['POLICY_ENGINE_ENABLED'] = '1'
os.environ['LITELLM_URL'] = 'http://litellm:4000'

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4010")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")


@pytest.fixture(scope="session")
def client():
    headers = {"Authorization": f"Bearer {MASTER_KEY}"} if MASTER_KEY else {}
    with httpx.Client(base_url=GATEWAY_URL, headers=headers, timeout=30) as c:
        yield c


@pytest.fixture(scope="session")
def first_model(client):
    """Return the first available model ID (without AI-Gateway: prefix)."""
    resp = client.get("/v1/models")
    resp.raise_for_status()
    models = resp.json().get("data", [])
    if not models:
        pytest.skip("no models available")
    raw = models[0]["id"]
    return raw.removeprefix("AI-Gateway:")


@pytest_asyncio.fixture
async def asgi_client(monkeypatch):
    """Provides an httpx.AsyncClient hooked directly to the Translator ASGI app, bypassing network."""
    
    # Setup fakeredis for the translator
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(translator_main, "_redis", fake_redis)
    # Env vars are already set in the module header
    
    # Ensure policy engine evaluates correctly if needed or set defaults
    
    # Mock Litellm requests via respx? The issue says: "Setup respx router"
    # Actually, respx_mock is a standard fixture provided by respx.
    
    # Initialize globals normally set in _lifespan
    translator_main._client = httpx.AsyncClient()
    translator_main.LITELLM = "http://litellm:4000"
    translator_main._policy_evaluator = translator_main.PolicyEvaluator.from_env()
    
    async with ASGITransport(app=app) as transport:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            yield c
    
    await translator_main._client.aclose()


# --- LiteLLM respx mocks ---
LITELLM_URL = os.environ.get("LITELLM_URL", "http://litellm:4000")

@pytest.fixture
def mock_litellm_router():
    """Provides a base respx router mocking common LiteLLM endpoints.
    Can be overridden by individual tests."""
    with respx.mock(base_url=LITELLM_URL, assert_all_called=False) as router:
        router.get("/health/readiness").mock(return_value=httpx.Response(200, json={"status": "healthy"}))
        router.get("/health").mock(return_value=httpx.Response(200, json={"status": "healthy"}))
        
        router.get("/v1/models").mock(return_value=httpx.Response(200, json={
            "data": [
                {"id": "gpt-4", "object": "model", "created": 123456789, "owned_by": "openai"}
            ]
        }))
        
        def _chat_completion_mock(request):
            import json
            try:
                body = json.loads(request.content)
                agent_id = body.get("metadata", {}).get("agent_id")
                if agent_id == "test:seed-429-counter":
                    return httpx.Response(429, json={"error": "too many requests"})
            except:
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

@pytest.fixture
def asgi_client_sync(monkeypatch):
    """Provides a synchronous TestClient hooked directly to the Translator ASGI app."""
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(translator_main, "_redis", fake_redis)
    monkeypatch.setattr(translator_main, "CACHE_ENABLED", True)
    monkeypatch.setattr(translator_main, "POLICY_MOCK_SCENARIOS", True)
    monkeypatch.setattr(translator_main, "POLICY_ENGINE_ENABLED", True)
    
    with TestClient(app=app, base_url="http://testserver") as c:
        yield c
