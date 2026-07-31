"""Contract tests for deterministic multi-account credential balancing (#561)."""

from core.credential_balancing import CredentialPoolMember, select_credential


def _pool(*members: tuple[str, str, int]):
    return [CredentialPoolMember(credential_id=cid, status=status, weight=weight) for cid, status, weight in members]


def test_selection_is_repeatable_for_same_request_key():
    pool = _pool(("cred-a", "HEALTHY", 1), ("cred-b", "HEALTHY", 1))
    assert select_credential(pool, request_key="session-7") == select_credential(pool, request_key="session-7")


def test_unhealthy_and_deprioritized_members_are_excluded():
    pool = _pool(("cred-a", "RATE_LIMITED", 100), ("cred-b", "HEALTHY", 1), ("cred-c", "HEALTHY", 1))
    for key in ("a", "b", "c", "d"):
        assert select_credential(pool, request_key=key, deprioritized={"cred-b"}) == "cred-c"


def test_weighted_selection_is_fair_over_many_keys():
    pool = _pool(("cred-heavy", "HEALTHY", 3), ("cred-light", "HEALTHY", 1))
    picks = [select_credential(pool, request_key=f"request-{index}") for index in range(400)]
    heavy = picks.count("cred-heavy")
    assert 250 <= heavy <= 350


def test_empty_eligible_pool_returns_none():
    assert select_credential(_pool(("cred-a", "SUSPENDED", 1)), request_key="x") is None
