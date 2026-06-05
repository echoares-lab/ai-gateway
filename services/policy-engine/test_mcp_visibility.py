"""Unit tests for MCP visibility resolver (issue 38-20)."""

from __future__ import annotations

import os
from unittest.mock import patch

from evaluator.mcp_visibility import (
    extract_mcp_config,
    resolve_mcp_visibility,
)
from main import evaluate
from profile_store import ProfileStore
from schemas import (
    EvaluateRequest,
    PolicyProfile,
    PolicyScope,
    RoutingContext,
    TenancyContext,
)


def _profile(
    scope: PolicyScope,
    scope_id: str,
    *,
    policy_json: dict | None = None,
) -> PolicyProfile:
    return PolicyProfile(
        profile_id=f"prof-{scope_id}",
        scope=scope,
        scope_id=scope_id,
        policy_json=policy_json or {},
    )


def test_no_mcp_policy_allows_all():
    profiles = [_profile(PolicyScope.REPO, "gateway")]
    result = resolve_mcp_visibility(profiles)
    assert result.allowed_mcp_servers is None
    assert result.denied_mcp_servers == []
    assert result.rules_applied == []


def test_allowlist_from_most_specific_profile():
    profiles = [
        _profile(
            PolicyScope.ORG,
            "echoares",
            policy_json={"mcp": {"mode": "allowlist", "servers": ["mcp-brave"]}},
        ),
        _profile(
            PolicyScope.REPO,
            "gateway",
            policy_json={"mcp": {"mode": "allowlist", "servers": ["mcp-git", "mcp-fetch"]}},
        ),
    ]
    result = resolve_mcp_visibility(profiles)
    assert result.allowed_mcp_servers == ["mcp-git", "mcp-fetch"]
    assert "mcp:allowlist:2" in result.rules_applied


def test_denylist_with_registry_computes_allowed():
    profiles = [
        _profile(
            PolicyScope.TEAM,
            "eng",
            policy_json={"mcp": {"mode": "denylist", "servers": ["mcp-postgres"]}},
        ),
    ]
    registered = ["mcp-git", "mcp-fetch", "mcp-postgres"]
    result = resolve_mcp_visibility(profiles, registered_mcp_servers=registered)
    assert result.allowed_mcp_servers == ["mcp-git", "mcp-fetch"]
    assert result.denied_mcp_servers == ["mcp-postgres"]
    assert "mcp:hidden:mcp-postgres" in result.rules_applied


def test_empty_denylist_allows_all():
    profiles = [
        _profile(
            PolicyScope.WORKSPACE,
            "core",
            policy_json={"mcp": {"mode": "denylist", "servers": []}},
        ),
    ]
    result = resolve_mcp_visibility(profiles, registered_mcp_servers=["mcp-git"])
    assert result.allowed_mcp_servers is None
    assert result.rules_applied == []


def test_legacy_mcp_allowlist_supported():
    profiles = [_profile(PolicyScope.REPO, "gateway", policy_json={"mcp_allowlist": ["mcp-git"]})]
    config = extract_mcp_config(profiles)
    assert config == {"mode": "allowlist", "servers": ["mcp-git"]}


def test_denylist_without_registry_emits_denied_only():
    profiles = [
        _profile(
            PolicyScope.REPO,
            "audit",
            policy_json={"mcp": {"mode": "denylist", "servers": ["mcp-postgres"]}},
        ),
    ]
    with patch.dict(os.environ, {}, clear=True):
        result = resolve_mcp_visibility(profiles)
    assert result.allowed_mcp_servers is None
    assert result.denied_mcp_servers == ["mcp-postgres"]


def test_evaluate_injects_mcp_visibility_into_decision():
    store = ProfileStore(
        None,
        enabled=False,
        profiles={
            ("repo", "gateway"): _profile(
                PolicyScope.REPO,
                "gateway",
                policy_json={"mcp": {"mode": "allowlist", "servers": ["mcp-git"]}},
            ),
        },
    )
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        tenancy=TenancyContext(repo_name="gateway"),
    )
    decision = evaluate(
        EvaluateRequest(context=ctx),
        profile_store=store,
    )
    assert decision.allowed_mcp_servers == ["mcp-git"]
    assert "mcp:allowlist:1" in decision.rules_applied


def test_evaluate_mcp_metadata_round_trip():
    store = ProfileStore(
        None,
        enabled=False,
        profiles={
            ("repo", "gateway"): _profile(
                PolicyScope.REPO,
                "gateway",
                policy_json={"mcp": {"mode": "allowlist", "servers": ["mcp-fetch"]}},
            ),
        },
    )
    ctx = RoutingContext(
        requested_model="claude-sonnet-4-6",
        tenancy=TenancyContext(repo_name="gateway"),
    )
    decision = evaluate(EvaluateRequest(context=ctx), profile_store=store)
    meta = decision.to_metadata()
    assert meta["allowed_mcp_servers"] == ["mcp-fetch"]
