"""Executable fixtures for the C-SVC-2 client config generation contract."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_CONTRACT = {
    "route": "/v1/config/generate",
    "scope": "config:generate",
    "flag": "CONFIG_GENERATION_API_ENABLED",
    "clients": ("cursor", "claude-code", "codex", "gemini", "openai-sdk", "all"),
    "profiles": ("cursor", "claude-code", "codex", "gemini", "openai-sdk"),
    "defaults": {
        "base_url": "http://localhost:4000",
        "key_var": "AI_GATEWAY_KEY",
        "org": "echoares",
        "workspace": "core",
        "team": "eng",
        "repo": "my-repo",
        "env": "dev",
    },
    "limits": {"request_bytes": 8192, "response_bytes": 65536, "idempotency_key_chars": 128},
    "errors": {
        "disabled": (404, "config_generation_disabled"),
        "unauthorized": (401, "config_auth_required"),
        "forbidden": (403, "config_scope_forbidden"),
        "invalid": (400, "invalid_request"),
        "request_too_large": (413, "request_too_large"),
        "response_too_large": (413, "response_too_large"),
        "duplicate_same": (200, None),
        "duplicate_different": (409, "idempotency_conflict"),
    },
}

_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY_VAR = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
_FORBIDDEN_OUTPUT_MARKERS = (
    "authorization:",
    "bearer ",
    "refresh_token",
    "oauth_token",
    "credential_json",
    "/home/",
    "/root/",
    "file://",
)


def _normalize_base_url(value: str) -> str:
    """Reference validation/normalization used by parity fixtures."""
    if not isinstance(value, str) or not value or len(value.encode()) > 512:
        raise ValueError("invalid base URL")
    if any(ord(char) < 32 for char in value) or ".." in value:
        raise ValueError("invalid base URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("invalid base URL")
    if parsed.query or parsed.fragment:
        raise ValueError("invalid base URL")
    normalized = value.rstrip("/")
    if normalized.endswith("/v1"):
        normalized = normalized[:-3].rstrip("/")
    return normalized or f"{parsed.scheme}://{parsed.netloc}"


def _validate_request(request: dict) -> dict:
    if set(request) - {"client", "base_url", "key_var", "org", "workspace", "team", "repo", "env"}:
        raise ValueError("unknown field")
    values = {**_CONTRACT["defaults"], **request}
    if values["client"] not in _CONTRACT["clients"]:
        raise ValueError("invalid client")
    values["base_url"] = _normalize_base_url(values["base_url"])
    if not _KEY_VAR.fullmatch(values["key_var"]):
        raise ValueError("invalid key variable")
    for field in ("org", "workspace", "team", "repo", "env"):
        if not _SAFE_LABEL.fullmatch(values[field]):
            raise ValueError(f"invalid {field}")
    return values


def _reference_render(request: dict) -> dict:
    values = _validate_request(request)
    tenant = "ak-" + "-".join(values[field] for field in ("org", "workspace", "team", "repo", "env"))
    key_ref = "${" + values["key_var"] + "}"
    profiles = {
        "cursor": f"Base URL: {values['base_url']}/v1\nAPI Key: {key_ref}\nTenant label: {tenant}\n",
        "claude-code": f'export ANTHROPIC_BASE_URL="{values["base_url"]}"\nexport ANTHROPIC_API_KEY="{key_ref}"\n',
        "codex": f'openai_base_url = "{values["base_url"]}/v1"\n# Auth: {key_ref}\n',
        "gemini": f'export GEMINI_BASE_URL="{values["base_url"]}/v1beta"\nexport GEMINI_API_KEY="{key_ref}"\n',
        "openai-sdk": f'base_url="{values["base_url"]}/v1"\napi_key="{key_ref}"\n',
    }
    selected = profiles if values["client"] == "all" else {values["client"]: profiles[values["client"]]}
    return {
        "schema_version": "client-config.v1",
        "client": values["client"],
        "base_url": values["base_url"],
        "key_var": values["key_var"],
        "tenant_key_example": tenant,
        "content_type": "text/plain",
        "profiles": selected,
    }


def test_route_scope_flag_and_allowlist_are_explicit():
    assert _CONTRACT["route"] == "/v1/config/generate"
    assert _CONTRACT["scope"] == "config:generate"
    assert _CONTRACT["flag"].endswith("_API_ENABLED")
    assert _CONTRACT["clients"] == ("cursor", "claude-code", "codex", "gemini", "openai-sdk", "all")


def test_source_precedence_and_defaults_are_stable():
    defaults = _CONTRACT["defaults"]
    assert defaults == {
        "base_url": "http://localhost:4000",
        "key_var": "AI_GATEWAY_KEY",
        "org": "echoares",
        "workspace": "core",
        "team": "eng",
        "repo": "my-repo",
        "env": "dev",
    }
    result = _validate_request({"client": "codex", "team": "platform"})
    assert result["team"] == "platform"
    assert result["repo"] == defaults["repo"]
    assert "os.environ" not in repr(result)


@pytest.mark.parametrize("base_url", ["https://gateway.example/v1/", "http://localhost:4000////"])
def test_base_url_normalization_is_origin_safe(base_url):
    normalized = _normalize_base_url(base_url)
    assert normalized in {"https://gateway.example", "http://localhost:4000"}
    for bad in (
        "javascript:alert(1)",
        "https://user:password@gateway.example",
        "https://gateway.example?token=secret",
        "https://gateway.example#fragment",
        "https://gateway.example/../etc",
        "https://gateway.example/\nX-Leak: yes",
    ):
        with pytest.raises(ValueError):
            _normalize_base_url(bad)


def test_labels_and_key_variables_reject_shell_or_path_syntax():
    with pytest.raises(ValueError):
        _validate_request({"client": "cursor", "key_var": "${SECRET}"})
    with pytest.raises(ValueError):
        _validate_request({"client": "cursor", "repo": "../../etc"})
    with pytest.raises(ValueError):
        _validate_request({"client": "unknown"})
    with pytest.raises(ValueError):
        _validate_request({"client": "cursor", "unexpected": "value"})


def test_reference_output_is_deterministic_placeholder_only_and_ordered():
    request = {"client": "all", "base_url": "https://gateway.example/v1", "org": "acme"}
    first = _reference_render(request)
    second = _reference_render(request)
    assert first == second
    assert list(first["profiles"]) == list(_CONTRACT["profiles"])
    rendered = " ".join(first["profiles"].values())
    assert "${AI_GATEWAY_KEY}" in rendered
    assert all(marker not in rendered.lower() for marker in _FORBIDDEN_OUTPUT_MARKERS)
    assert "ak-acme-core-eng-my-repo-dev" in rendered
    assert "secret-value" not in rendered


def test_hard_limits_and_failure_matrix_are_contractual():
    assert _CONTRACT["limits"] == {"request_bytes": 8192, "response_bytes": 65536, "idempotency_key_chars": 128}
    assert _CONTRACT["errors"]["disabled"] == (404, "config_generation_disabled")
    assert _CONTRACT["errors"]["unauthorized"] == (401, "config_auth_required")
    assert _CONTRACT["errors"]["duplicate_different"] == (409, "idempotency_conflict")


def test_contract_document_requires_openapi_and_rollback_without_routes():
    # The gateway unit-test image intentionally copies only the service tree;
    # run this assertion locally when the repository docs are available.
    path = Path(__file__)
    if len(path.parents) < 3:
        pytest.skip("repository docs are not mounted in the service test image")
    document = path.parents[2] / "docs" / "CLIENT_CONFIG_GENERATION_CONTRACT.md"
    if not document.exists():
        pytest.skip("repository docs are not mounted in the service test image")
    text = document.read_text()
    assert "POST /v1/config/generate" in text
    assert "docs/openapi/gateway-engine.yaml" in text
    assert "gen-client-config.sh" in text
    assert "CONFIG_GENERATION_API_ENABLED=false" in text
    assert "No implementation" in text or "do not add a route" in text
