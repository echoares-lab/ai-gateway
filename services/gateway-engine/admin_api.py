import os
import httpx
import logging
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("gateway_engine.admin_api")

router = APIRouter()

def _get_config():
    litellm_url = os.environ.get("LITELLM_URL", "http://litellm:4000")
    return {
        "admin_url": os.environ.get("LITELLM_ADMIN_URL", litellm_url).rstrip("/"),
        "admin_key": os.environ.get("ADMIN_API_KEY", "").strip(),
        "master_key": os.environ.get("LITELLM_MASTER_KEY", "").strip(),
    }

def _require_admin_key(request: Request, config: dict) -> JSONResponse | None:
    admin_key = config["admin_key"]
    if not admin_key:
        log.warning("ADMIN_API_KEY not configured, blocking admin access")
        return JSONResponse(
            {"error": {"message": "ADMIN_API_KEY not configured", "code": "admin_key_missing"}},
            status_code=503
        )
    if request.headers.get("x-admin-key") != admin_key:
        return JSONResponse(
            {"error": {"message": "Unauthorized", "code": "unauthorized"}},
            status_code=403
        )
    return None

async def _proxy_to_litellm(method: str, path: str, request: Request):
    config = _get_config()
    auth_error = _require_admin_key(request, config)
    if auth_error:
        return auth_error

    headers = {}
    master_key = config["master_key"]
    if master_key:
        headers["Authorization"] = f"Bearer {master_key}"
    
    content = await request.body()
    url = f"{config['admin_url']}/{path}"
    params = dict(request.query_params)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method,
                url,
                content=content,
                headers=headers,
                params=params
            )
            try:
                return JSONResponse(content=resp.json(), status_code=resp.status_code)
            except Exception:
                # Fallback for non-JSON responses
                return JSONResponse(
                    content={"raw_response": resp.text}, 
                    status_code=resp.status_code
                )
    except Exception as exc:
        log.error("Proxy to LiteLLM admin failed: %s", exc)
        return JSONResponse(
            {"error": {"message": f"Proxy failed: {exc}", "code": "proxy_error"}},
            status_code=502
        )

@router.get("/admin/teams")
async def get_teams(request: Request):
    """Proxy to LiteLLM team/list."""
    return await _proxy_to_litellm("GET", "team/list", request)

@router.post("/admin/teams")
async def create_team(request: Request):
    """Proxy to LiteLLM team/new."""
    return await _proxy_to_litellm("POST", "team/new", request)

@router.post("/admin/keys")
async def create_key(request: Request):
    """Proxy to LiteLLM key/generate."""
    return await _proxy_to_litellm("POST", "key/generate", request)
