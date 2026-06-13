import logging
import os

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("gateway-engine.admin")

_legacy_admin_key_warned = False

_AUTH_HEADER_NAMES = frozenset({"authorization", "api-key", "x-api-key"})


def resolve_gateway_admin_key() -> str:
    """Return configured gateway admin key (GATEWAY_ENGINE_ADMIN_KEY preferred)."""
    global _legacy_admin_key_warned
    key = os.environ.get("GATEWAY_ENGINE_ADMIN_KEY", "").strip()
    if key:
        return key
    legacy = os.environ.get("ADMIN_API_KEY", "").strip()
    if legacy:
        if not _legacy_admin_key_warned:
            log.warning("ADMIN_API_KEY is deprecated; set GATEWAY_ENGINE_ADMIN_KEY instead")
            _legacy_admin_key_warned = True
        return legacy
    return ""


def _get_config():
    litellm_url = os.environ.get("LITELLM_URL", "http://litellm:4000")
    return {
        "admin_url": os.environ.get("LITELLM_ADMIN_URL", litellm_url).rstrip("/"),
        "admin_key": resolve_gateway_admin_key(),
        "master_key": os.environ.get("LITELLM_MASTER_KEY", "").strip(),
    }


def _admin_key_valid(request: Request, configured: str | None = None) -> bool:
    key = configured if configured is not None else resolve_gateway_admin_key()
    if not key:
        return False
    return request.headers.get("x-admin-key", "") == key


def _require_admin_key(request: Request, config: dict | None = None) -> JSONResponse | None:
    configured = resolve_gateway_admin_key()
    if config is not None and config.get("admin_key"):
        configured = str(config["admin_key"]).strip()
    if _admin_key_valid(request, configured):
        return None
    status = 403 if configured else 503
    message = (
        "gateway-engine admin mutations are disabled or unauthorized"
        if configured
        else "GATEWAY_ENGINE_ADMIN_KEY not configured"
    )
    return JSONResponse(
        {"error": {"message": message, "code": "admin_key_required"}},
        status_code=status,
    )


def admin_read_auth_enabled() -> bool:
    return os.environ.get("GATEWAY_ENGINE_ADMIN_READ_AUTH", "").lower() in (
        "1",
        "true",
        "yes",
    )


def _require_admin_read_access(request: Request) -> JSONResponse | None:
    if not admin_read_auth_enabled():
        return None
    return _require_admin_key(request)


def _admin_error(code: str, message: str, location: str) -> dict:
    return {"code": code, "message": message, "location": location}
