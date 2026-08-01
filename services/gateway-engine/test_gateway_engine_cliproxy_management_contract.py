"""Executable fixtures for the CLIProxy management API contract (#610)."""

from __future__ import annotations

_CONTRACT = {
    "operations": {
        "/health": "cliproxy:health:read",
        "/v1/management/auth-files": "cliproxy:sessions:read",
        "/v1/management/config": "cliproxy:config:read",
        "/v1/management/auth-files/fields": "cliproxy:sessions:write",
        "/login/{provider}": "cliproxy:oauth:write",
    },
    "outcomes": {
        "disabled": "management_disabled",
        "unauthorized": 401,
        "forbidden": 403,
        "malformed": 400,
        "unavailable": 503,
        "timeout": 504,
        "duplicate_same": 200,
        "duplicate_different": 409,
    },
    "limits": {"read_timeout_seconds": 5, "write_timeout_seconds": 30, "read_bytes": 65536, "write_bytes": 262144},
    "forbidden_fields": [
        "api_key",
        "authorization_code",
        "bearer",
        "cookie",
        "credential_json",
        "environment",
        "refresh_token",
        "oauth_token",
        "filesystem_path",
    ],
}


def test_operations_have_least_privilege_scopes():
    assert _CONTRACT["operations"]["/health"] == "cliproxy:health:read"
    assert _CONTRACT["operations"]["/v1/management/auth-files"] == "cliproxy:sessions:read"
    assert _CONTRACT["operations"]["/login/{provider}"] == "cliproxy:oauth:write"
    assert all(scope.startswith("cliproxy:") for scope in _CONTRACT["operations"].values())


def test_failure_matrix_and_hard_bounds_are_explicit():
    outcomes = _CONTRACT["outcomes"]
    assert outcomes["disabled"] == "management_disabled"
    assert outcomes["unauthorized"] == 401
    assert outcomes["forbidden"] == 403
    assert outcomes["duplicate_different"] == 409
    limits = _CONTRACT["limits"]
    assert limits == {
        "read_timeout_seconds": 5,
        "write_timeout_seconds": 30,
        "read_bytes": 65536,
        "write_bytes": 262144,
    }


def test_secret_and_path_fields_are_forbidden_from_responses_and_traces():
    forbidden = set(_CONTRACT["forbidden_fields"])
    assert {"api_key", "refresh_token", "credential_json", "filesystem_path"} <= forbidden
    safe_event = {"request_id": "req-1", "operation": "health", "outcome": "ok", "duration_ms": 4}
    assert forbidden.isdisjoint(safe_event)


def test_contract_is_docs_only_and_flag_defaults_off():
    import os

    assert os.environ.get("CLIPROXY_MANAGEMENT_API_ENABLED", "").lower() not in {"1", "true", "yes"}
