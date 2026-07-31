"""Contract tests for idempotent credential inventory reconciliation (#557)."""

from core.credential_inventory import CredentialInventoryRecord, reconcile_credentials


def _record(status: str, credential_id: str = "cred-1") -> CredentialInventoryRecord:
    return CredentialInventoryRecord(
        credential_id=credential_id,
        provider="anthropic",
        label="operator",
        key_fingerprint="fp",
        status=status,
    )


def test_reconcile_is_idempotent_for_unchanged_pool():
    records, transitions = reconcile_credentials([_record("HEALTHY")], {"cred-1": "HEALTHY"})
    assert records[0].status == "HEALTHY"
    assert transitions == []


def test_reconcile_does_not_resurrect_operator_suspended_credential():
    records, transitions = reconcile_credentials([_record("HEALTHY")], {"cred-1": "SUSPENDED"})
    assert records[0].status == "SUSPENDED"
    assert transitions == []


def test_reconcile_emits_one_redacted_transition_for_real_change():
    records, transitions = reconcile_credentials([_record("CRITICAL")], {"cred-1": "HEALTHY"})
    assert records[0].status == "CRITICAL"
    assert len(transitions) == 1
    assert transitions[0].reason == "credential_status_critical"
    assert "operator" not in transitions[0].reason
