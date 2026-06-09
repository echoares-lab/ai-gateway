from fastapi import Request
from fastapi.responses import JSONResponse
import os

def _get_config():
    litellm_url = os.environ.get("LITELLM_URL", "http://litellm:4000")
    return {
        "admin_url": os.environ.get("LITELLM_ADMIN_URL", litellm_url).rstrip("/"),
        "admin_key": os.environ.get("ADMIN_API_KEY", "").strip(),
        "master_key": os.environ.get("LITELLM_MASTER_KEY", "").strip(),
    }

def _require_admin_key(request: Request, config: dict = None) -> JSONResponse | None:
    if config is None:
        config = _get_config()
    admin_key = config["admin_key"]
    if not admin_key:
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

def _admin_error(code: str, message: str, location: str) -> dict:
    return {"code": code, "message": message, "location": location}
