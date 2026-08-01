"""Safe, deterministic client configuration generation endpoint."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import OrderedDict
from urllib.parse import urlsplit

from core.admin_shared import resolve_gateway_admin_key
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}
_FLAG_NAMES = ("CONFIG_GENERATION_API_ENABLED", "GATEWAY_ENGINE_CONFIG_GENERATION_API_ENABLED")
_SCOPE = "config:generate"
_MAX_REQUEST_BYTES = 8 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_IDEMPOTENCY_KEY = 128
_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
_CACHE_MAX_ENTRIES = 256
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY_VAR = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
_SECRET_MARKER = re.compile(r"(?i)(?:bearer\s|sk-|refresh[_-]?token|oauth[_-]?token|api[_-]?key|password|secret)")
_REAL_SECRET_VALUE = re.compile(
    r"(?i)(?:bearer\s+(?!\$\{[A-Z_][A-Z0-9_]*\})[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9._-]{8,}|"
    r"(?:refresh[_-]?token|oauth[_-]?token|password|secret)\s*[:=]\s*[^\s,}]+)"
)
_CLIENTS = ("cursor", "claude-code", "codex", "gemini", "openai-sdk", "all")
_PROFILES = ("cursor", "claude-code", "codex", "gemini", "openai-sdk")
_SCRIPT_DEFAULTS = {
    "base_url": "http://localhost:4000",
    "key_var": "AI_GATEWAY_KEY",
    "org": "echoares",
    "workspace": "core",
    "team": "eng",
    "repo": "my-repo",
    "env": "dev",
}
_IDEMPOTENCY_CACHE: OrderedDict[str, tuple[float, str, dict]] = OrderedDict()


def _enabled() -> bool:
    for name in _FLAG_NAMES:
        raw = os.environ.get(name)
        if raw is not None:
            return raw.strip().lower() not in {"", "0", "false", "no", "off"}
    return False


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code, headers=_NO_STORE)


def _auth_error(request: Request) -> JSONResponse | None:
    configured = resolve_gateway_admin_key()
    if not configured or request.headers.get("x-admin-key", "") != configured:
        return _error("config_auth_required", "Configuration generation authentication required", 401)
    if request.headers.get("x-management-scope", "") != _SCOPE:
        return _error("config_scope_forbidden", "Configuration generation scope is not permitted", 403)
    return None


def _service_defaults() -> dict[str, str]:
    """Read only explicitly named, non-secret service defaults."""
    values = dict(_SCRIPT_DEFAULTS)
    names = {
        "base_url": "CONFIG_GENERATION_DEFAULT_BASE_URL",
        "key_var": "CONFIG_GENERATION_DEFAULT_KEY_VAR",
        "org": "CONFIG_GENERATION_DEFAULT_ORG",
        "workspace": "CONFIG_GENERATION_DEFAULT_WORKSPACE",
        "team": "CONFIG_GENERATION_DEFAULT_TEAM",
        "repo": "CONFIG_GENERATION_DEFAULT_REPO",
        "env": "CONFIG_GENERATION_DEFAULT_ENV",
    }
    for field, env_name in names.items():
        raw = os.environ.get(env_name)
        if raw is not None and raw != "":
            values[field] = raw
    return values


def _normalize_base_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value.encode()) > 512:
        raise ValueError("base_url")
    if any(ord(char) < 32 for char in value) or ".." in value or "/root/" in value or "/home/" in value:
        raise ValueError("base_url")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("base_url")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url")
    normalized = value.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3].rstrip("/")
    return normalized or f"{parsed.scheme}://{parsed.netloc}"


def _validate(request_data: object) -> dict[str, str]:
    if not isinstance(request_data, dict):
        raise ValueError("body")
    allowed = {"client", "base_url", "key_var", "org", "workspace", "team", "repo", "env"}
    if set(request_data) - allowed:
        raise ValueError("field")
    values = {**_service_defaults(), **request_data}
    if values["client"] not in _CLIENTS:
        raise ValueError("client")
    values["base_url"] = _normalize_base_url(values["base_url"])
    if not isinstance(values["key_var"], str) or not _KEY_VAR.fullmatch(values["key_var"]):
        raise ValueError("key_var")
    for field in ("org", "workspace", "team", "repo", "env"):
        value = values[field]
        if not isinstance(value, str) or not _SAFE_LABEL.fullmatch(value) or _SECRET_MARKER.search(value):
            raise ValueError(field)
    return values


def _tenant_label(values: dict[str, str]) -> str:
    return "ak-" + "-".join(values[field] for field in ("org", "workspace", "team", "repo", "env"))


def _render_profiles(values: dict[str, str]) -> OrderedDict[str, str]:
    base = values["base_url"]
    key_ref = "${" + values["key_var"] + "}"
    tenant = _tenant_label(values)
    profiles = OrderedDict(
        (
            (
                "cursor",
                "\n".join(
                    (
                        "Cursor (Settings → Models → OpenAI API)",
                        f"Base URL:    {base}/v1",
                        f"API Key:     {key_ref}",
                        "Model name:  AI-Gateway:claude-sonnet-4-6",
                        f"Tenant label: {tenant}",
                    )
                )
                + "\n",
            ),
            (
                "claude-code",
                f'export ANTHROPIC_BASE_URL="{base}"\nexport ANTHROPIC_API_KEY="{key_ref}"\n',
            ),
            (
                "codex",
                f'openai_base_url = "{base}/v1"\n# Auth: Authorization: Bearer {key_ref}\n',
            ),
            (
                "gemini",
                f'export GEMINI_BASE_URL="{base}/v1beta"\nexport GEMINI_API_KEY="{key_ref}"\n',
            ),
            (
                "openai-sdk",
                f'base_url="{base}/v1"\napi_key="{key_ref}"\n',
            ),
        )
    )
    return profiles


def _render(values: dict[str, str]) -> dict:
    profiles = _render_profiles(values)
    selected = profiles if values["client"] == "all" else OrderedDict(((values["client"], profiles[values["client"]]),))
    body = {
        "schema_version": "client-config.v1",
        "client": values["client"],
        "base_url": values["base_url"],
        "key_var": values["key_var"],
        "tenant_key_example": _tenant_label(values),
        "content_type": "text/plain",
    }
    if values["client"] == "all":
        body["profiles"] = selected
    else:
        body["config"] = selected[values["client"]]
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > _MAX_RESPONSE_BYTES:
        raise OverflowError
    # A final belt-and-suspenders check protects future renderer edits.
    text = encoded.decode()
    if _REAL_SECRET_VALUE.search(text) or any(path in text for path in ("/root/", "/home/", "file://")):
        raise RuntimeError("unsafe_render")
    return body


def _idempotency_result(key: str | None, request_hash: str, body: dict) -> JSONResponse | None:
    if key is None:
        return None
    now = time.monotonic()
    while _IDEMPOTENCY_CACHE and next(iter(_IDEMPOTENCY_CACHE.values()))[0] <= now:
        _IDEMPOTENCY_CACHE.popitem(last=False)
    previous = _IDEMPOTENCY_CACHE.get(key)
    if previous is not None:
        if previous[1] != request_hash:
            return _error("idempotency_conflict", "Idempotency key was used for another request", 409)
        return JSONResponse(previous[2], headers=_NO_STORE)
    _IDEMPOTENCY_CACHE[key] = (now + _IDEMPOTENCY_TTL_SECONDS, request_hash, body)
    _IDEMPOTENCY_CACHE.move_to_end(key)
    while len(_IDEMPOTENCY_CACHE) > _CACHE_MAX_ENTRIES:
        _IDEMPOTENCY_CACHE.popitem(last=False)
    return None


@router.post("/v1/config/generate")
async def generate_client_config(request: Request):
    if not _enabled():
        return _error("config_generation_disabled", "Configuration generation is disabled", 404)
    if error := _auth_error(request):
        return error
    raw = await request.body()
    if len(raw) > _MAX_REQUEST_BYTES:
        return _error("request_too_large", "Configuration request exceeded the limit", 413)
    try:
        request_data = json.loads(raw or b"{}")
        values = _validate(request_data)
        body = _render(values)
    except (json.JSONDecodeError, ValueError):
        return _error("invalid_request", "Configuration request is invalid", 400)
    except OverflowError:
        return _error("response_too_large", "Generated configuration exceeded the limit", 413)
    except Exception:
        return _error("config_generation_error", "Configuration generation failed", 500)

    idem_key = request.headers.get("idempotency-key")
    if idem_key is not None:
        if not 1 <= len(idem_key) <= _MAX_IDEMPOTENCY_KEY or any(
            ord(char) < 33 or ord(char) > 126 for char in idem_key
        ):
            return _error("invalid_request", "Configuration request is invalid", 400)
        request_hash = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if replay := _idempotency_result(idem_key, request_hash, body):
            return replay
    return JSONResponse(body, headers=_NO_STORE)
