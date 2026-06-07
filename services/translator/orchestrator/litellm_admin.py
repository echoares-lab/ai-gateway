import os
import httpx
import logging

log = logging.getLogger("translator.orchestrator.litellm_admin")

LITELLM_ADMIN_URL = os.environ.get("LITELLM_ADMIN_URL", "http://litellm:4000").rstrip("/")
_client: httpx.AsyncClient | None = None

def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client

async def litellm_admin_get(path: str, *, params: dict | None = None) -> dict | None:
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not master_key:
        log.warning("LITELLM_MASTER_KEY not configured")
        return None
    
    headers = {"Authorization": f"Bearer {master_key}"}
    try:
        client = get_client()
        resp = await client.get(
            f"{LITELLM_ADMIN_URL}{path}",
            headers=headers,
            params=params,
        )
        if resp.status_code != 200:
            log.warning("LiteLLM admin GET %s failed with status %d", path, resp.status_code)
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.error("LiteLLM admin GET %s failed: %s", path, exc)
        return None

async def litellm_admin_post(path: str, json_data: dict) -> dict | None:
    master_key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not master_key:
        log.warning("LITELLM_MASTER_KEY not configured")
        return None
    
    headers = {"Authorization": f"Bearer {master_key}"}
    try:
        client = get_client()
        resp = await client.post(
            f"{LITELLM_ADMIN_URL}{path}",
            headers=headers,
            json=json_data,
        )
        if resp.status_code not in (200, 201):
            log.warning("LiteLLM admin POST %s failed with status %d: %s", path, resp.status_code, resp.text)
            return None
        data = resp.json()
        return data if isinstance(data, dict) else None
    except Exception as exc:
        log.error("LiteLLM admin POST %s failed: %s", exc)
        return None
