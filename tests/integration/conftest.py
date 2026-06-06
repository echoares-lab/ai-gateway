import os
import pytest
import pytest_asyncio
import httpx
import respx
from dotenv import load_dotenv

import fakeredis.aioredis
from httpx import ASGITransport

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../services/translator')))
from main import app
import main as translator_main

load_dotenv()

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
    monkeypatch.setattr(translator_main, "CACHE_ENABLED", True)
    
    # Ensure policy engine evaluates correctly if needed or set defaults
    
    # Mock Litellm requests via respx? The issue says: "Setup respx router"
    # Actually, respx_mock is a standard fixture provided by respx.
    
    async with ASGITransport(app=app) as transport:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            yield c

