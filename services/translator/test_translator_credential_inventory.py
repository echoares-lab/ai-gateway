"""Unit tests for translator credential inventory admin APIs."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import main as t
from core.credential_inventory import CredentialInventoryListResponse, CredentialInventoryRecord


class _FakeCredentialStore:
    enabled = True

    def __init__(self, existing: dict[str, str] | None = None):
        self._existing = existing or {}
        self.credentials: list[CredentialInventoryRecord] = []

    def list_credentials(self):
        return CredentialInventoryListResponse(
            registry_available=True,
            credentials=[
                CredentialInventoryRecord(
                    credential_id="cred-1",
                    provider="anthropic",
                    label="operator@example.com",
                    key_fingerprint="abc123secretfingerprint",
                    status="HEALTHY",
                    metadata={
                        "status_message": "ok",
                        "recent_requests": [{"prompt": "secret"}],
                    },
                )
            ],
        )

    def existing_statuses(self):
        return dict(self._existing)

    def upsert_credentials(self, credentials):
        self.credentials = list(credentials)
        return len(credentials)


class _FakeResponse:
    status_code = 200

    def json(self):
        return {
            "files": [
                {
                    "id": "claude-mock.json",
                    "provider": "claude",
                    "label": "operator@example.com",
                    "auth_index": "abc123secretfingerprint",
                    "status": "error",
                    "failed": 3,
                    "status_message": "401 invalid token",
                    "updated_at": "2026-06-06T13:00:00Z",
                    "recent_requests": [{"prompt": "secret"}],
                }
            ]
        }


class _FakeHttpClient:
    def __init__(self):
        self.requests = []

    async def get(self, url, headers=None, timeout=None):
        self.requests.append({"url": url, "headers": headers, "timeout": timeout})
        return _FakeResponse()


def test_admin_credentials_redacts_inventory(monkeypatch):
    monkeypatch.setattr(t, "_credential_inventory_store", lambda: _FakeCredentialStore())

    client = TestClient(t.app)
    resp = client.get("/admin/credentials")

    assert resp.status_code == 200
    cred = resp.json()["credentials"][0]
    assert cred["credential_id"] == "cred-1"
    assert cred["label"] == "[redacted]"
    assert cred["key_fingerprint"] == "[redacted]"
    assert "recent_requests" not in cred["metadata"]


def test_admin_credentials_sync_requires_admin_key(monkeypatch):
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "")
    monkeypatch.delenv("TRANSLATOR_ADMIN_KEY", raising=False)

    client = TestClient(t.app)
    resp = client.post("/admin/credentials/sync", json={"dry_run": True})

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "admin_key_required"


def test_admin_credentials_sync_dry_run_fetches_cliproxy_and_redacts(monkeypatch):
    store = _FakeCredentialStore(existing={"claude-mock.json": "HEALTHY"})
    fake_client = _FakeHttpClient()
    monkeypatch.setattr(t, "_credential_inventory_store", lambda: store)
    monkeypatch.setattr(t, "_client", fake_client)
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")
    monkeypatch.setattr(t, "CLIPROXY_MANAGEMENT_KEY", "mgmt-key")
    monkeypatch.setattr(t, "CLIPROXY_URL", "http://cliproxy:8317")

    client = TestClient(t.app)
    resp = client.post(
        "/admin/credentials/sync",
        headers={"x-admin-key": "test-admin"},
        json={"dry_run": True},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["discovered_count"] == 1
    assert body["imported_count"] == 1
    assert body["credentials"][0]["provider"] == "anthropic"
    assert body["credentials"][0]["status"] == "CRITICAL"
    assert body["credentials"][0]["label"] == "[redacted]"
    assert body["transitions"][0]["previous_status"] == "HEALTHY"
    assert fake_client.requests[0]["headers"] == {"x-management-key": "mgmt-key"}
    assert store.credentials == []


def test_admin_credentials_sync_apply_writes_and_emits_policy_event(monkeypatch):
    store = _FakeCredentialStore(existing={"claude-mock.json": "HEALTHY"})
    emitted = []
    monkeypatch.setattr(t, "_credential_inventory_store", lambda: store)
    monkeypatch.setattr(t, "_client", _FakeHttpClient())
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")
    monkeypatch.setattr(t, "CLIPROXY_MANAGEMENT_KEY", "mgmt-key")

    async def fake_emit(transition):
        emitted.append(transition)
        return True

    monkeypatch.setattr(t, "_emit_credential_transition_to_policy", fake_emit)

    client = TestClient(t.app)
    resp = client.post(
        "/admin/credentials/sync",
        headers={"x-admin-key": "test-admin"},
        json={"dry_run": False},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["imported_count"] == 1
    assert store.credentials[0].credential_id == "claude-mock.json"
    assert store.credentials[0].status == "CRITICAL"
    assert len(emitted) == 1
    assert emitted[0].new_status == "CRITICAL"


def test_admin_credential_probe_is_documented_unsupported(monkeypatch):
    monkeypatch.setattr(t, "TRANSLATOR_ADMIN_KEY", "test-admin")

    client = TestClient(t.app)
    resp = client.post(
        "/admin/credentials/cred-1/probe",
        headers={"x-admin-key": "test-admin"},
    )

    assert resp.status_code == 501
    assert resp.json()["errors"][0]["code"] == "targeted_probe_unsupported"


def test_credential_event_shape_for_policy(monkeypatch):
    captured = {}

    async def fake_process(event):
        captured["event"] = event
        return True

    monkeypatch.setattr(t, "process_credential_event_async", fake_process)
    transition = t.CredentialTransition(
        credential_id="cred-1",
        provider="anthropic",
        previous_status="HEALTHY",
        new_status="CRITICAL",
        reason="401",
        cool_down_until=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )

    result = asyncio.run(t._emit_credential_transition_to_policy(transition))

    assert result is True
    assert captured["event"].credential_id == "cred-1"
    assert captured["event"].previous_status == "HEALTHY"
    assert captured["event"].new_status == "CRITICAL"
