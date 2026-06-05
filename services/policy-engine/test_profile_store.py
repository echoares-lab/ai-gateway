"""Unit tests for Postgres policy_profiles read layer (issue 38-5)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import fakeredis

from main import app, get_profile_store
from profile_store import ProfileStore, scope_ids_for_tenancy
from redis_store import RedisStateStore
from schemas import PolicyProfile, PolicyScope, TenancyContext


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _sample_row() -> tuple:
    return (
        "prof-gateway",
        "repo",
        "gateway",
        ["claude-sonnet-4-6"],
        ["gpt-5-4"],
        ["claude-sonnet-4-6", "claude-haiku-4-5"],
        "native",
        {"mcp_allowlist": ["filesystem"]},
        True,
    )


def test_scope_ids_for_tenancy_resolution_order():
    tenancy = TenancyContext(
        tenant_id="echoares",
        workspace_id="core",
        team_id="eng",
        repo_name="gateway",
    )
    pairs = scope_ids_for_tenancy(tenancy)
    assert pairs == [
        (PolicyScope.ORG, "echoares"),
        (PolicyScope.WORKSPACE, "core"),
        (PolicyScope.TEAM, "eng"),
        (PolicyScope.REPO, "gateway"),
    ]


def test_fixture_store_get_profile():
    profile = PolicyProfile(
        profile_id="prof-gateway",
        scope=PolicyScope.REPO,
        scope_id="gateway",
        denied_models=["gpt-5-4"],
    )
    store = ProfileStore(None, enabled=False, profiles={("repo", "gateway"): profile})
    loaded = store.get_profile(PolicyScope.REPO, "gateway")
    assert loaded is not None
    assert loaded.profile_id == "prof-gateway"


def test_get_profiles_for_tenancy_skips_missing_scopes():
    team_profile = PolicyProfile(
        profile_id="prof-eng",
        scope=PolicyScope.TEAM,
        scope_id="eng",
        allowed_models=["claude-sonnet-4-6"],
    )
    store = ProfileStore(None, enabled=False, profiles={("team", "eng"): team_profile})
    tenancy = TenancyContext(team_id="eng", repo_name="missing-repo")
    profiles = store.get_profiles_for_tenancy(tenancy)
    assert len(profiles) == 1
    assert profiles[0].scope == PolicyScope.TEAM


def test_postgres_get_profile_reads_row():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = _sample_row()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    store = ProfileStore(lambda: mock_conn)
    profile = store.get_profile("repo", "gateway")
    assert profile is not None
    assert profile.allowed_models == ["claude-sonnet-4-6"]
    assert profile.denied_models == ["gpt-5-4"]
    assert profile.fallback_chain_override == ["claude-sonnet-4-6", "claude-haiku-4-5"]
    assert profile.credential_tier_preference == "native"
    mock_cur.execute.assert_called_once()


def test_postgres_fail_open_on_query_error():
    mock_conn = MagicMock()
    mock_conn.cursor.side_effect = RuntimeError("connection lost")
    store = ProfileStore(lambda: mock_conn)
    assert store.get_profile("repo", "gateway") is None


def test_profiles_api_returns_fixture_profile(client: TestClient):
    profile = PolicyProfile(
        profile_id="prof-gateway",
        scope=PolicyScope.REPO,
        scope_id="gateway",
        allowed_models=["claude-sonnet-4-6"],
    )
    store = ProfileStore(None, enabled=False, profiles={("repo", "gateway"): profile})
    app.dependency_overrides[get_profile_store] = lambda: store
    try:
        response = client.get("/v1/profiles/repo/gateway")
        assert response.status_code == 200
        body = response.json()
        assert body["profile_id"] == "prof-gateway"
        assert body["allowed_models"] == ["claude-sonnet-4-6"]
    finally:
        app.dependency_overrides.clear()


def test_redis_profile_cache_round_trip():
    client = fakeredis.FakeRedis(decode_responses=True)
    redis_store = RedisStateStore(client)
    profile = PolicyProfile(
        profile_id="prof-gateway",
        scope=PolicyScope.REPO,
        scope_id="gateway",
        denied_models=["gpt-5-4"],
    )
    redis_store.set_profile_cache(
        "repo",
        "gateway",
        profile.model_dump(mode="json"),
    )
    store = ProfileStore(None, enabled=False)
    loaded = store.get_profile("repo", "gateway", redis_store=redis_store)
    assert loaded is not None
    assert loaded.denied_models == ["gpt-5-4"]


def test_profiles_api_404_when_missing(client: TestClient):
    store = ProfileStore(None, enabled=False)
    app.dependency_overrides[get_profile_store] = lambda: store
    try:
        response = client.get("/v1/profiles/repo/unknown")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
