"""Mock boundary tests for credential remapping integration (#562)."""

from core.policy.agent_affinity import _pick_credential
from core.policy.schemas import RoutingContext


def test_pool_metadata_remaps_to_healthy_weighted_member():
    context = RoutingContext(
        requested_model="gpt-test",
        agent_id="agent-1",
        session_id="session-1",
        metadata={
            "credential_pool": [
                {"credential_id": "cred-disabled", "status": "SUSPENDED", "weight": 100},
                {"credential_id": "cred-live", "status": "HEALTHY", "weight": 1},
            ]
        },
    )
    assert _pick_credential(context, []) == "cred-live"


def test_management_snapshot_failure_fails_open_to_existing_candidate():
    context = RoutingContext(
        requested_model="gpt-test",
        metadata={
            "credential_pool": "unavailable",
            "credential_id": "cred-current",
            "credential_candidates": ["cred-current"],
        },
    )
    assert _pick_credential(context, []) == "cred-current"


def test_all_members_unhealthy_fails_open_to_existing_candidate():
    context = RoutingContext(
        requested_model="gpt-test",
        metadata={
            "credential_pool": [{"credential_id": "cred-hot", "status": "RATE_LIMITED"}],
            "credential_id": "cred-current",
        },
    )
    assert _pick_credential(context, []) == "cred-current"
