"""Tests for the opt-in, read-only CLIProxy management adapter."""

import admin_api
import httpx
import pytest
from fastapi.testclient import TestClient
from main import app


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, headers=None):
        self.calls.append((url, headers))
        if self.error:
            raise self.error
        return self.response


def _headers(scope, *, key="admin-secret"):
    return {"x-admin-key": key, "x-management-scope": scope}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("CLIPROXY_MANAGEMENT_API_ENABLED", "true")
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-secret")
    monkeypatch.setenv("CLIPROXY_MANAGEMENT_KEY", "upstream-secret")
    monkeypatch.setenv("CLIPROXY_URL", "http://cliproxy.test:8317")


def test_management_is_disabled_without_upstream_call(monkeypatch):
    monkeypatch.delenv("CLIPROXY_MANAGEMENT_API_ENABLED", raising=False)
    monkeypatch.delenv("GATEWAY_ENGINE_CLIPROXY_MANAGEMENT_API_ENABLED", raising=False)
    fake = _FakeClient(error=AssertionError("disabled route must not call upstream"))
    monkeypatch.setattr(admin_api.httpx, "AsyncClient", lambda **_kwargs: fake)
    response = TestClient(app).get(
        "/admin/cliproxy/health",
        headers=_headers("cliproxy:health:read"),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "management_disabled"


def test_management_requires_operator_key_and_scope(configured):
    client = TestClient(app)
    missing = client.get("/admin/cliproxy/health", headers={"x-management-scope": "cliproxy:health:read"})
    assert missing.status_code == 401
    wrong_scope = client.get(
        "/admin/cliproxy/health",
        headers=_headers("cliproxy:config:read"),
    )
    assert wrong_scope.status_code == 403


def test_management_redacts_payload_and_forwards_management_key(monkeypatch, configured):
    fake = _FakeClient(
        httpx.Response(
            200,
            json={
                "status": "ok",
                "version": "1.2.3",
                "files": [
                    {
                        "provider": "claude",
                        "status": "ready",
                        "token": "oauth-secret",
                        "path": "/home/operator/.cli-proxy-api/auth.json",
                    }
                ],
            },
            request=httpx.Request("GET", "http://cliproxy.test:8317/v0/management/auth-files"),
        )
    )
    monkeypatch.setattr(admin_api.httpx, "AsyncClient", lambda **_kwargs: fake)
    response = TestClient(app).get(
        "/admin/cliproxy/auth-files",
        headers=_headers("cliproxy:sessions:read"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["files"][0]["token"] == "[redacted]"
    assert body["files"][0]["path"] == "[redacted]"
    assert "oauth-secret" not in response.text
    assert fake.calls[0][1] == {"x-management-key": "upstream-secret"}


@pytest.mark.parametrize(
    ("response", "expected", "code"),
    [
        (httpx.Response(401, request=httpx.Request("GET", "http://cliproxy.test")), 502, "upstream_auth_failure"),
        (httpx.Response(500, request=httpx.Request("GET", "http://cliproxy.test")), 502, "management_upstream_error"),
        (
            httpx.Response(200, content=b"not-json", request=httpx.Request("GET", "http://cliproxy.test")),
            502,
            "management_malformed_response",
        ),
    ],
)
def test_management_maps_upstream_failures(monkeypatch, configured, response, expected, code):
    fake = _FakeClient(response)
    monkeypatch.setattr(admin_api.httpx, "AsyncClient", lambda **_kwargs: fake)
    result = TestClient(app).get(
        "/admin/cliproxy/config",
        headers=_headers("cliproxy:config:read"),
    )
    assert result.status_code == expected
    assert result.json()["error"]["code"] == code


def test_management_maps_timeout_and_oversize(monkeypatch, configured):
    fake_timeout = _FakeClient(error=httpx.ReadTimeout("upstream timeout"))
    monkeypatch.setattr(admin_api.httpx, "AsyncClient", lambda **_kwargs: fake_timeout)
    timeout = TestClient(app).get(
        "/admin/cliproxy/health",
        headers=_headers("cliproxy:health:read"),
    )
    assert timeout.status_code == 504
    assert timeout.json()["error"]["code"] == "management_timeout"

    oversize = httpx.Response(
        200,
        content=b"{" + b"a" * (admin_api._CLIPROXY_RESPONSE_LIMIT + 1) + b"}",
        request=httpx.Request("GET", "http://cliproxy.test"),
    )
    monkeypatch.setattr(admin_api.httpx, "AsyncClient", lambda **_kwargs: _FakeClient(oversize))
    too_large = TestClient(app).get(
        "/admin/cliproxy/health",
        headers=_headers("cliproxy:health:read"),
    )
    assert too_large.status_code == 502
    assert too_large.json()["error"]["code"] == "management_response_too_large"
