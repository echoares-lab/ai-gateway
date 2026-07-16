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
            "credentials": [_sample_quota_cred(id="cred-x", provider="moonshot-custom", label="m@example.com")]
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


def test_admin_quota_status_maps_live_status_and_fetched_at(monkeypatch):
    fetched = "2026-07-16T12:00:00Z"
    fake = _FakeQuotaHttpClient(
        quota_status={"credentials": [_sample_quota_cred()]},
        quota_status_full={
            "credentials": [
                {
                    "id": "cred-claude-1",
                    "status": "fresh",
                    "fetched_at": fetched,
                    "plan_type": "max",
                    "windows": {
                        "five_hour": {"utilization_pct": 10.0, "resets_at": "2026-07-11T15:00:00Z"},
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
    assert body["partial"] is False
    quota = body["accounts"][0]["quota"]
    assert quota["live_status"] == "fresh"
    assert quota["live_fetched_at"] == fetched
    assert "full_quota_error" not in quota


def test_admin_quota_status_live_fetched_at_omitted_unless_success(monkeypatch):
    fake = _FakeQuotaHttpClient(
        quota_status={"credentials": [_sample_quota_cred()]},
        quota_status_full={
            "credentials": [
                {
                    "id": "cred-claude-1",
                    "status": "error",
                    "error": "anthropic returned 503",
                    "windows": {},
                }
            ]
        },
        auth_files={
            "files": [
                {
                    "id": "cred-claude-1",
                    "email": "operator@example.com",
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
    assert body["partial"] is True
    quota = body["accounts"][0]["quota"]
    assert quota["live_status"] == "error"
    assert quota.get("live_fetched_at") is None
    assert "live_fetched_at" not in quota or quota["live_fetched_at"] is None
    assert quota["full_quota_error"] == "anthropic returned 503"


def test_admin_quota_status_normalizes_sentinel_resets_to_null(monkeypatch):
    fake = _FakeQuotaHttpClient(
        quota_status={
            "credentials": [
                _sample_quota_cred(
                    resets_at="0001-01-01T00:00:00Z",
                    captured_at="1970-01-01T00:00:00Z",
                )
            ]
        },
        quota_status_full={
            "credentials": [
                {
                    "id": "cred-claude-1",
                    "status": "fresh",
                    "fetched_at": "2026-07-16T12:00:00Z",
                    "windows": {
                        "five_hour": {
                            "utilization_pct": 10.0,
                            "resets_at": "0001-01-01T00:00:00Z",
                        },
                        "seven_day": {
                            "utilization_pct": 20.0,
                            "resets_at": "1970-01-01T00:00:00Z",
                        },
                    },
                }
            ]
        },
        auth_files={
            "files": [
                {
                    "id": "cred-claude-1",
                    "email": "operator@example.com",
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
    quota = resp.json()["accounts"][0]["quota"]
    assert quota["captured_at"] is None
    assert quota["windows"]["binding"]["resets_at"] is None
    assert quota["windows"]["five_hour"]["resets_at"] is None
    assert quota["windows"]["seven_day"]["resets_at"] is None


def test_admin_quota_status_partial_only_for_active_missing_or_error(monkeypatch):
    fake = _FakeQuotaHttpClient(
        quota_status={
            "credentials": [
                _sample_quota_cred(id="cred-active-ok", provider="claude", label="ok@example.com"),
                _sample_quota_cred(id="cred-active-err", provider="claude", label="err@example.com"),
                _sample_quota_cred(id="cred-disabled-err", provider="codex", label="off@example.com"),
                _sample_quota_cred(id="cred-unsupported", provider="kimi", label="kimi@example.com"),
            ]
        },
        quota_status_full={
            "credentials": [
                {
                    "id": "cred-active-ok",
                    "status": "fresh",
                    "fetched_at": "2026-07-16T12:00:00Z",
                    "windows": {},
                },
                {
                    "id": "cred-active-err",
                    "status": "missing",
                    "error": "credential has no access token",
                    "windows": {},
                },
                {
                    "id": "cred-disabled-err",
                    "status": "error",
                    "error": "chatgpt returned 503",
                    "windows": {},
                },
                {
                    "id": "cred-unsupported",
                    "status": "unsupported",
                    "error": "provider does not support live quota",
                    "windows": {},
                },
            ]
        },
        auth_files={
            "files": [
                {"id": "cred-active-ok", "email": "ok@example.com", "status": "active", "disabled": False},
                {"id": "cred-active-err", "email": "err@example.com", "status": "active", "disabled": False},
                {"id": "cred-disabled-err", "email": "off@example.com", "status": "disabled", "disabled": True},
                {"id": "cred-unsupported", "email": "kimi@example.com", "status": "active", "disabled": False},
            ]
        },
    )
    _configure(monkeypatch, fake)

    client = TestClient(t.app)
    resp = client.get("/admin/quota/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["partial"] is True
    by_id = {a["credential_id"]: a for a in body["accounts"]}
    assert by_id["cred-active-ok"]["quota"]["live_status"] == "fresh"
    assert by_id["cred-active-err"]["quota"]["live_status"] == "missing"
    assert by_id["cred-disabled-err"]["quota"]["live_status"] == "error"
    assert by_id["cred-unsupported"]["quota"]["live_status"] == "unsupported"


def test_admin_quota_status_not_partial_for_disabled_or_unsupported_only(monkeypatch):
    fake = _FakeQuotaHttpClient(
        quota_status={
            "credentials": [
                _sample_quota_cred(id="cred-disabled", provider="claude", label="off@example.com"),
                _sample_quota_cred(id="cred-unsupported", provider="kimi", label="kimi@example.com"),
            ]
        },
        quota_status_full={
            "credentials": [
                {
                    "id": "cred-disabled",
                    "status": "error",
                    "error": "anthropic returned 503",
                    "windows": {},
                },
                {
                    "id": "cred-unsupported",
                    "status": "unsupported",
                    "error": "provider does not support live quota",
                    "windows": {},
                },
            ]
        },
        auth_files={
            "files": [
                {"id": "cred-disabled", "email": "off@example.com", "status": "disabled", "disabled": True},
                {"id": "cred-unsupported", "email": "kimi@example.com", "status": "active", "disabled": False},
            ]
        },
    )
    _configure(monkeypatch, fake)

    client = TestClient(t.app)
    resp = client.get("/admin/quota/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["partial"] is False


def test_admin_quota_status_full_endpoint_failure_keeps_accounts_not_502(monkeypatch):
    """Passive accounts remain usable; do not broaden 502 to full-only failures."""
    fake = _FakeQuotaHttpClient(
        quota_status={"credentials": [_sample_quota_cred()]},
        raise_on={"full"},
        auth_files={
            "files": [
                {
                    "id": "cred-claude-1",
                    "email": "operator@example.com",
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
    assert len(body["accounts"]) == 1
    assert body["errors"]
    assert any(
        "quota-status/full" in (e.get("source") or e.get("location") or "") for e in body["errors"]
    )
    # Without a live full entry, treat active credential as missing for partial.
    assert body["accounts"][0]["quota"]["live_status"] == "missing"
    assert body["partial"] is True
