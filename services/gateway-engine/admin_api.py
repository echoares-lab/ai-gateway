import logging
from pathlib import Path

import httpx
from core.admin_shared import _get_config, _require_admin_key
from core.config import config as runtime_config
from core.launcher_key_escrow import OpenBaoEscrowClient
from core.launcher_key_service import LauncherKeyResult, LauncherKeyService, LauncherKeyServiceError
from core.onboarding.onboarding_service import onboarding_service
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

log = logging.getLogger("gateway-engine.admin_api")

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}
_SERVICE_ERROR_STATUS = {
    "key_alias_not_found": 404,
    "key_secret_not_escrowed": 409,
    "key_identity_mismatch": 409,
    "secret_store_unavailable": 503,
    "key_creation_incomplete": 502,
}
_SERVICE_ERROR_MESSAGES = {
    "key_alias_not_found": "Key alias was not found",
    "key_secret_not_escrowed": "Key secret is not escrowed",
    "key_identity_mismatch": "Stored key identity does not match",
    "secret_store_unavailable": "Secret store is unavailable",
    "key_creation_incomplete": "Key creation is incomplete",
}
_service_instance: LauncherKeyService | None = None


class CreateKeyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    key_alias: str
    team_id: str


class ImportKeyRequest(BaseModel):
    key: str


class StableKeyResponse(BaseModel):
    key_alias: str
    key: str
    team_id: str
    key_id: str


def _valid_alias(alias: str) -> bool:
    if not 1 <= len(alias) <= 200 or any(char.isspace() or ord(char) < 32 for char in alias):
        return False
    parts = alias.split("/")
    return all(part not in ("", ".", "..") and all(char.isalnum() or char in "._-" for char in part) for part in parts)


def _error_response(code: str) -> JSONResponse:
    safe_code = code if code in _SERVICE_ERROR_STATUS else "key_creation_incomplete"
    return JSONResponse(
        {"error": {"code": safe_code, "message": _SERVICE_ERROR_MESSAGES[safe_code]}},
        status_code=_SERVICE_ERROR_STATUS[safe_code],
        headers=_NO_STORE,
    )


def _auth_error(request: Request) -> JSONResponse | None:
    error = _require_admin_key(request, _get_config())
    if error is not None:
        error.headers.update(_NO_STORE)
    return error


def _result_response(result: LauncherKeyResult) -> JSONResponse:
    body = StableKeyResponse(
        key_alias=result.alias,
        key=result.token,
        team_id=result.team_id,
        key_id=result.litellm_key_id,
    )
    return JSONResponse(body.model_dump(), headers=_NO_STORE)


async def _validated_body(request: Request, model: type[BaseModel]) -> BaseModel | JSONResponse:
    try:
        return model.model_validate(await request.json())
    except (ValueError, TypeError, ValidationError):
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": "Request body is invalid"}},
            status_code=422,
            headers=_NO_STORE,
        )


def _launcher_key_service() -> LauncherKeyService:
    """Build the process-wide stable-key service without exposing credentials."""
    global _service_instance
    if _service_instance is not None:
        return _service_instance
    if not runtime_config.secret_store_availability().available:
        raise LauncherKeyServiceError("secret_store_unavailable", "Secret store is unavailable")

    client = httpx.AsyncClient()

    async def workload_token() -> str:
        try:
            jwt = Path("/var/run/secrets/kubernetes.io/serviceaccount/token").read_text().strip()
            response = await client.post(
                f"{runtime_config.OPENBAO_ADDR.rstrip('/')}/v1/auth/{runtime_config.OPENBAO_AUTH_MOUNT.strip('/')}/login",
                json={"role": runtime_config.OPENBAO_ROLE, "jwt": jwt},
                timeout=runtime_config.OPENBAO_TIMEOUT,
            )
            response.raise_for_status()
            return str(response.json()["auth"]["client_token"])
        except Exception:
            return ""

    escrow = OpenBaoEscrowClient(
        http_client=client,
        address=runtime_config.OPENBAO_ADDR,
        kv_mount=runtime_config.OPENBAO_KV_MOUNT,
        key_prefix=runtime_config.OPENBAO_KEY_PREFIX,
        workload_token_supplier=workload_token,
        timeout=runtime_config.OPENBAO_TIMEOUT,
    )
    _service_instance = LauncherKeyService(
        escrow=escrow,
        litellm_http_client=client,
        litellm_admin_url=runtime_config.LITELLM_ADMIN_URL,
        litellm_master_key=runtime_config.LITELLM_MASTER_KEY,
    )
    return _service_instance


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
    """Create a stable virtual key using write-ahead secret escrow."""
    if error := _auth_error(request):
        return error
    create_request = await _validated_body(request, CreateKeyRequest)
    if isinstance(create_request, JSONResponse):
        return create_request
    assert isinstance(create_request, CreateKeyRequest)
    if not _valid_alias(create_request.key_alias):
        return JSONResponse(
            {"error": {"code": "invalid_key_alias", "message": "Key alias is invalid"}},
            status_code=422,
            headers=_NO_STORE,
        )
    try:
        result = await _launcher_key_service().create_key(create_request.model_dump())
    except LauncherKeyServiceError as exc:
        return _error_response(exc.code)
    return _result_response(result)


@router.get("/admin/keys/{alias:path}/secret")
async def recover_key(request: Request, alias: str):
    """Recover an existing stable virtual-key secret by alias."""
    if error := _auth_error(request):
        return error
    if not _valid_alias(alias):
        return JSONResponse(
            {"error": {"code": "invalid_key_alias", "message": "Key alias is invalid"}},
            status_code=422,
            headers=_NO_STORE,
        )
    try:
        result = await _launcher_key_service().recover_key(alias)
    except LauncherKeyServiceError as exc:
        return _error_response(exc.code)
    return _result_response(result)


@router.post("/admin/keys/{alias:path}/import")
async def import_key(request: Request, alias: str):
    """Import and verify the original token for a pre-escrow key alias."""
    if error := _auth_error(request):
        return error
    if not _valid_alias(alias):
        return JSONResponse(
            {"error": {"code": "invalid_key_alias", "message": "Key alias is invalid"}},
            status_code=422,
            headers=_NO_STORE,
        )
    import_request = await _validated_body(request, ImportKeyRequest)
    if isinstance(import_request, JSONResponse):
        return import_request
    assert isinstance(import_request, ImportKeyRequest)
    try:
        result = await _launcher_key_service().import_key(alias, import_request.key)
    except LauncherKeyServiceError as exc:
        return _error_response(exc.code)
    return _result_response(result)


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
