import os
import sys
from typing import Any

import httpx
from api.admin_routes import _admin_error, _model_registry_store
from core.admin_shared import _require_admin_key
from core.model_registry import (
    LiteLLMRuntimeMutationResult,
    ModelDeleteRequest,
    ModelHotAddResponse,
    ModelHotDeleteResponse,
    ModelRegistryWriteRequest,
)
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


def _main_attr(name: str, default):
    main_module = sys.modules.get("main")
    return getattr(main_module, name, default) if main_module is not None else default


def _litellm_runtime_url(path: str) -> str:
    litellm_url = str(_main_attr("LITELLM", os.environ.get("LITELLM_URL", "http://litellm:4000"))).rstrip("/")
    return f"{litellm_url}/{path.lstrip('/')}"


def _litellm_model_new_payload(model) -> dict[str, Any]:
    litellm_params: dict[str, Any] = {"model": model.litellm_model}
    api_base = model.policy_metadata.get("api_base")
    if api_base:
        litellm_params["api_base"] = api_base
    info: dict[str, Any] = {}
    if model.supports_tools is not None:
        info["supports_function_calling"] = model.supports_tools
    if model.supports_vision is not None:
        info["supports_vision"] = model.supports_vision
    if model.max_input_tokens is not None:
        info["max_input_tokens"] = model.max_input_tokens
    if model.max_output_tokens is not None:
        info["max_output_tokens"] = model.max_output_tokens
    payload: dict[str, Any] = {
        "model_name": model.model_id,
        "litellm_params": litellm_params,
    }
    if info:
        payload["model_info"] = info
    return payload


async def _post_litellm_runtime_mutation(path: str, payload: dict[str, Any]) -> LiteLLMRuntimeMutationResult:
    client = _main_attr("_client", None)
    if client is None:
        return LiteLLMRuntimeMutationResult(
            ok=False,
            reason="http client not initialized",
        )
    master_key = os.environ.get("LITELLM_MASTER_KEY", "").strip()
    headers = {"authorization": f"Bearer {master_key}"} if master_key else {}
    try:
        resp = await client.post(
            _litellm_runtime_url(path),
            headers=headers,
            json=payload,
            timeout=10.0,
        )
    except (httpx.HTTPError, Exception) as exc:
        return LiteLLMRuntimeMutationResult(
            ok=False,
            reason=f"{type(exc).__name__}: {exc}",
        )
    try:
        body = resp.json()
    except Exception:
        body = {"raw_response": getattr(resp, "text", "")}
    ok = 200 <= resp.status_code < 300
    return LiteLLMRuntimeMutationResult(
        ok=ok,
        status_code=resp.status_code,
        body=body if isinstance(body, dict) else {"response": body},
        reason=None if ok else f"litellm runtime API returned {resp.status_code}",
    )


@router.post("/model/new", response_model=ModelHotAddResponse)
async def model_new(request: Request, body: ModelRegistryWriteRequest):
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error
    store = _model_registry_store()
    if not store.enabled:
        return ModelHotAddResponse(
            accepted=False,
            registry_available=False,
            partial_success=False,
            litellm_add=LiteLLMRuntimeMutationResult(
                ok=False,
                reason="skipped because model registry is unavailable",
            ),
            errors=[
                _admin_error(
                    "registry_unavailable",
                    "DATABASE_URL or psycopg2 unavailable",
                    "postgres:model_registry",
                )
            ],
        )
    try:
        model = store.upsert_model(body.to_record())
    except Exception as exc:
        return ModelHotAddResponse(
            accepted=False,
            registry_available=store.enabled,
            partial_success=False,
            litellm_add=LiteLLMRuntimeMutationResult(ok=False, reason="registry write failed"),
            errors=[
                _admin_error(
                    "registry_write_error",
                    f"{type(exc).__name__}: {exc}",
                    "postgres:model_registry",
                )
            ],
        )

    litellm_add = await _post_litellm_runtime_mutation("model/new", _litellm_model_new_payload(model))
    errors = []
    if not litellm_add.ok:
        errors.append(
            _admin_error(
                "litellm_runtime_add_failed",
                litellm_add.reason or "unknown runtime add failure",
                "litellm:/model/new",
            )
        )
    return ModelHotAddResponse(
        accepted=True,
        registry_available=True,
        partial_success=not litellm_add.ok,
        model=model,
        litellm_add=litellm_add,
        errors=errors,
    )


@router.post("/model/delete", response_model=ModelHotDeleteResponse)
async def model_delete(request: Request, body: ModelDeleteRequest):
    auth_error = _require_admin_key(request)
    if auth_error is not None:
        return auth_error
    store = _model_registry_store()
    if not store.enabled:
        return ModelHotDeleteResponse(
            accepted=False,
            registry_available=False,
            partial_success=False,
            litellm_delete=LiteLLMRuntimeMutationResult(
                ok=False,
                reason="skipped because model registry is unavailable",
            ),
            errors=[
                _admin_error(
                    "registry_unavailable",
                    "DATABASE_URL or psycopg2 unavailable",
                    "postgres:model_registry",
                )
            ],
        )
    model = store.get_model(body.model_id)
    if model is None:
        return JSONResponse(
            ModelHotDeleteResponse(
                accepted=False,
                registry_available=store.enabled,
                partial_success=False,
                litellm_delete=LiteLLMRuntimeMutationResult(ok=False, reason="model not found"),
                errors=[
                    _admin_error(
                        "model_not_found",
                        f"{body.model_id} not found",
                        "postgres:model_registry",
                    )
                ],
            ).model_dump(mode="json"),
            status_code=404,
        )
    try:
        store.hard_delete_model(body.model_id)
    except Exception as exc:
        return ModelHotDeleteResponse(
            accepted=False,
            registry_available=store.enabled,
            partial_success=False,
            model=model,
            litellm_delete=LiteLLMRuntimeMutationResult(ok=False, reason="registry delete failed"),
            errors=[
                _admin_error(
                    "registry_write_error",
                    f"{type(exc).__name__}: {exc}",
                    "postgres:model_registry",
                )
            ],
        )

    litellm_delete = await _post_litellm_runtime_mutation(
        "model/delete",
        {"id": body.model_id, "model_name": body.model_id, "model": body.model_id},
    )
    errors = []
    if not litellm_delete.ok:
        errors.append(
            _admin_error(
                "litellm_runtime_delete_failed",
                litellm_delete.reason or "unknown runtime delete failure",
                "litellm:/model/delete",
            )
        )
    return ModelHotDeleteResponse(
        accepted=True,
        registry_available=True,
        partial_success=not litellm_delete.ok,
        model=model,
        litellm_delete=litellm_delete,
        errors=errors,
    )
