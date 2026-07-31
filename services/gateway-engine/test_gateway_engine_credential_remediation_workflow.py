"""Mock integration tests for the operator remediation endpoint (#569)."""

import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import main as t
from core.credential_inventory import CredentialInventoryListResponse, CredentialInventoryRecord


class _Store:
    enabled = True

    def __init__(self, status: str = "CRITICAL"):
        self.record = CredentialInventoryRecord(
            credential_id="cred-1",
            provider="anthropic",
            label="operator",
            key_fingerprint="fp",
            status=status,
        )
        self.writes: list[tuple[str, str]] = []

    def list_credentials(self):
        return CredentialInventoryListResponse(registry_available=True, credentials=[self.record])

    def remediate_status(self, credential_id: str, status: str):
        self.writes.append((credential_id, status))
        self.record = self.record.model_copy(update={"status": status})
        return True


def test_remediation_endpoint_disables_credential_with_redacted_audit(monkeypatch):
    store = _Store()
    monkeypatch.setattr(t, "_credential_inventory_store", lambda: store)
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-test")
    response = TestClient(t.app).post(
        "/admin/credentials/cred-1/remediate",
        headers={"x-admin-key": "admin-test"},
        json={"action": "disable", "actor": "operator", "reason": "token=sk-secret rotate"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["new_status"] == "SUSPENDED"
    assert body["audit"]["reason"] == "token=[redacted] rotate"
    assert store.writes == [("cred-1", "SUSPENDED")]


def test_remediation_endpoint_rejects_invalid_transition_without_write(monkeypatch):
    store = _Store(status="CRITICAL")
    monkeypatch.setattr(t, "_credential_inventory_store", lambda: store)
    monkeypatch.setenv("GATEWAY_ENGINE_ADMIN_KEY", "admin-test")
    response = TestClient(t.app).post(
        "/admin/credentials/cred-1/remediate",
        headers={"x-admin-key": "admin-test"},
        json={"action": "enable", "actor": "operator", "reason": "manual"},
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is False
    assert response.json()["errors"][0]["code"] == "invalid_remediation"
    assert store.writes == []


def test_remediation_endpoint_requires_admin_key(monkeypatch):
    monkeypatch.delenv("GATEWAY_ENGINE_ADMIN_KEY", raising=False)
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    response = TestClient(t.app).post(
        "/admin/credentials/cred-1/remediate",
        json={"action": "disable", "actor": "operator", "reason": "manual"},
    )
    assert response.status_code == 503
