import logging

import httpx
from core.admin_shared import _get_config, _require_admin_key
from core.onboarding.onboarding_service import onboarding_service
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger("gateway-engine.admin_api")

router = APIRouter()


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
            resp = await client.request(method, url, content=content, headers=headers, params=params)
            try:
                return JSONResponse(content=resp.json(), status_code=resp.status_code)
            except Exception:
                return JSONResponse(content={"raw_response": resp.text}, status_code=resp.status_code)
    except Exception as exc:
        log.error("Proxy to LiteLLM admin failed: %s", exc)
        return JSONResponse({"error": {"message": f"Proxy failed: {exc}", "code": "proxy_error"}}, status_code=502)


# --- Legacy Proxy API ---


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


# --- Onboarding API ---


class RegisterTenantRequest(BaseModel):
    tenant_id: str
    email: str
    plan_id: str = "default"


@router.post("/admin/onboarding/register")
async def register_tenant(request: Request, register_request: RegisterTenantRequest):
    """
    Registers a new multi-tenant entry, provisioning necessary resources.
    Requires GATEWAY_ENGINE_ADMIN_KEY.
    """
    config = _get_config()
    auth_error = _require_admin_key(request, config)
    if auth_error:
        return auth_error

    result = await onboarding_service.register_tenant(
        tenant_id=register_request.tenant_id,
        email=register_request.email,
        plan_id=register_request.plan_id,
    )
    if result["success"]:
        return JSONResponse(content=result, status_code=200)
    else:
        return JSONResponse(content=result, status_code=500)
