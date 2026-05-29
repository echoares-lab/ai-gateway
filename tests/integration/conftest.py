import os
import pytest
import httpx
from dotenv import load_dotenv

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
