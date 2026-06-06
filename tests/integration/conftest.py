import os

import httpx
import pytest
from dotenv import load_dotenv

load_dotenv()

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4010")
MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
POLICY_ENGINE_URL = os.environ.get("POLICY_ENGINE_URL", "http://localhost:18080")


@pytest.fixture(autouse=True)
def reset_mock_policy_engine():
    """Reset mock policy-engine scenario state before each integration test."""
    if not POLICY_ENGINE_URL:
        yield
        return
    try:
        with httpx.Client(base_url=POLICY_ENGINE_URL, timeout=5) as pe:
            pe.post("/v1/debug/reset")
    except httpx.ConnectError:
        pass
    yield


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
