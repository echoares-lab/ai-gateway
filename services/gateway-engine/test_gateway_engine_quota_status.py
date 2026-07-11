"""Unit tests for GET /admin/quota/status."""

from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import main as t


class _JsonResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeQuotaHttpClient:
    """Routes CLIProxy management GETs by URL path."""

    def __init__(
        self,
        *,
        quota_status=None,
        quota_status_full=None,
        auth_files=None,
        raise_on=None,
        status_codes=None,
    ):
        self.quota_status = quota_status if quota_status is not None else {"credentials": []}
        self.quota_status_full = quota_status_full if quota_status_full is not None else {"credentials": []}
        self.auth_files = auth_files if auth_files is not None else {"files": []}
        self.raise_on = raise_on or set()
        self.status_codes = status_codes or {}
        self.requests = []

    async def get(self, url, headers=None, timeout=None):
        self.requests.append({"url": url, "headers": headers, "timeout": timeout})
        path = url.rsplit("/", 1)[-1]
        # Distinguish .../quota-status vs .../quota-status/full
        if url.rstrip("/").endswith("/quota-status/full") or url.endswith("quota-status/full"):
            key = "full"
            if key in self.raise_on:
                raise ConnectionError("cliproxy unreachable")
            return _JsonResponse(self.status_codes.get(key, 200), self.quota_status_full)
        if url.rstrip("/").endswith("/quota-status") or "quota-status" in url and "full" not in url:
            key = "quota"
            if key in self.raise_on:
                raise ConnectionError("cliproxy unreachable")
            return _JsonResponse(self.status_codes.get(key, 200), self.quota_status)
        if "auth-files" in url:
            key = "auth"
            if key in self.raise_on:
                raise ConnectionError("cliproxy unreachable")
            return _JsonResponse(self.status_codes.get(key, 200), self.auth_files)
        return _JsonResponse(404, {"error": "unexpected url"})


def _sample_quota_cred(**overrides):
    base = {
        "id": "cred-claude-1",
        "provider": "claude",
        "label": "operator@example.com",
        "utilization_pct": 45.0,
        "resets_at": "2026-07-11T14:00:00Z",
        "resets_in": "3h59m",
        "captured_at": "2026-07-11T10:00:00Z",
        "stale": False,
        "quota_source": "unified",
        "tokens_remaining": 1_100_000,
        "tokens_limit": 2_000_000,
        "requests_remaining": None,
        "requests_limit": None,
    }
    base.update(overrides)
    return base


def _configure(monkeypatch, fake_client, *, management_key="mgmt-key"):
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "CLIPROXY_URL", "http://cliproxy:8317")
    if management_key is None:
        monkeypatch.setattr(t, "CLIPROXY_MANAGEMENT_KEY", "")
        monkeypatch.delenv("CLIPROXY_MANAGEMENT_KEY", raising=False)
    else:
        monkeypatch.setattr(t, "CLIPROXY_MANAGEMENT_KEY", management_key)
        monkeypatch.setenv("CLIPROXY_MANAGEMENT_KEY", management_key)
    monkeypatch.delenv("GATEWAY_ENGINE_ADMIN_READ_AUTH", raising=False)


def test_admin_quota_status_happy_path_labels_and_scope(monkeypatch):
    fake = _FakeQuotaHttpClient(
        quota_status={"credentials": [_sample_quota_cred()]},
        quota_status_full={
            "credentials": [
                {
                    "id": "cred-claude-1",
                    "plan_type": "max",
                    "windows": {
                        "five_hour": {"utilization_pct": 10.0, "resets_at": "2026-07-11T15:00:00Z"},
                        "seven_day": {"utilization_pct": 20.0, "resets_at": "2026-07-18T10:00:00Z"},
                    },
                }
            ]
        },
        auth_files={
            "files": [
                {
                    "id": "cred-claude-1",
                    "email": "operator@example.com",
                    "provider": "claude",
                    "status": "active",
                    "disabled": False,
                }
            ]
        },
    )
    _configure(monkeypatch, fake)

    client = TestClient(t.app)
    resp = client.get("/admin/quota/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["accounts"]) == 1
    account = body["accounts"][0]
    assert account["provider"] == "claude"
    assert account["provider_label"] == "Claude"
    assert account["applies_to_models"] == "All Claude models"
    assert account["email"] == "operator@example.com"
    assert account["quota"]["stale"] is False
    assert account["quota"]["windows"]["binding"]["utilization_pct"] == 45.0
    assert account["quota"]["windows"]["five_hour"]["utilization_pct"] == 10.0
    assert account["quota"]["tokens_remaining"] == 1_100_000
    assert any("quota-status" in r["url"] for r in fake.requests)


def test_admin_quota_status_stale_flag_passthrough(monkeypatch):
    fake = _FakeQuotaHttpClient(
        quota_status={
            "credentials": [
                _sample_quota_cred(
                    stale=True,
                    utilization_pct=0,
                    tokens_remaining=0,
                    tokens_limit=0,
                )
            ]
        },
        quota_status_full={"credentials": [{"id": "cred-claude-1", "windows": {}}]},
        auth_files={"files": [{"id": "cred-claude-1", "email": "ops@example.com", "status": "active"}]},
    )
    _configure(monkeypatch, fake)

    client = TestClient(t.app)
    resp = client.get("/admin/quota/status")

    assert resp.status_code == 200
    quota = resp.json()["accounts"][0]["quota"]
    assert quota["stale"] is True
    # Stale + zero utilization is nullified by the handler
    assert quota["windows"]["binding"]["utilization_pct"] is None
    assert quota["tokens_remaining"] is None
    assert quota["tokens_limit"] is None


def test_admin_quota_status_cliproxy_unreachable_returns_502(monkeypatch):
    fake = _FakeQuotaHttpClient(raise_on={"quota", "full", "auth"})
    _configure(monkeypatch, fake)

    client = TestClient(t.app)
    resp = client.get("/admin/quota/status")

    assert resp.status_code == 502
    body = resp.json()
    assert body["status"] == "error"
    assert body["errors"]
    assert any(e.get("code") == "cliproxy_fetch_error" for e in body["errors"])


def test_admin_quota_status_missing_management_key_graceful_error(monkeypatch):
    fake = _FakeQuotaHttpClient(
        quota_status={"credentials": [_sample_quota_cred()]},
    )
    _configure(monkeypatch, fake, management_key=None)

    client = TestClient(t.app)
    resp = client.get("/admin/quota/status")

    assert resp.status_code == 502
    body = resp.json()
    assert body["status"] == "error"
    assert any(e.get("code") == "management_key_missing" for e in body["errors"])
    assert fake.requests == []


def test_admin_quota_status_unknown_provider_falls_back_to_raw(monkeypatch):
    fake = _FakeQuotaHttpClient(
        quota_status={
            "credentials": [
                _sample_quota_cred(id="cred-x", provider="moonshot-custom", label="m@example.com")
            ]
        },
        quota_status_full={"credentials": [{"id": "cred-x", "windows": {}}]},
        auth_files={"files": [{"id": "cred-x", "email": "m@example.com", "status": "active"}]},
    )
    _configure(monkeypatch, fake)

    client = TestClient(t.app)
    resp = client.get("/admin/quota/status")

    assert resp.status_code == 200
    account = resp.json()["accounts"][0]
    assert account["provider"] == "moonshot-custom"
    assert account["provider_label"] == "moonshot-custom"
    assert account["applies_to_models"] == "All moonshot-custom models"
