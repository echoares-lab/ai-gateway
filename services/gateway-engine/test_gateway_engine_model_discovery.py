"""Contract tests for model discovery reconciliation (C-MDL-1/#574)."""

import pytest
from core.model_discovery import DiscoveryDisposition, classify_discovery_result


@pytest.mark.parametrize("status", ["healthy", "ok", "available"])
def test_healthy_probe_applies_model(status):
    assert classify_discovery_result(status, currently_advertised=False) is DiscoveryDisposition.APPLY


@pytest.mark.parametrize(
    "status", ["timeout", "transient", "rate_limited", "auth_failure", "error", "malformed_response"]
)
def test_uncertain_probe_preserves_existing_model(status):
    assert classify_discovery_result(status, currently_advertised=True) is DiscoveryDisposition.PRESERVE


def test_missing_probe_removes_only_confirmed_missing_model():
    assert classify_discovery_result("missing_model", currently_advertised=True) is DiscoveryDisposition.REMOVE


def test_uncertain_probe_does_not_advertise_new_model():
    assert classify_discovery_result("timeout", currently_advertised=False) is DiscoveryDisposition.PRESERVE


def test_unknown_status_is_rejected():
    with pytest.raises(ValueError, match="unknown discovery probe status"):
        classify_discovery_result("future_status", currently_advertised=True)
