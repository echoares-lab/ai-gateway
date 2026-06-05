"""Unit tests for policy profile promotion validation (P0-7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from profile_promotion import (
    load_policy_profiles_file,
    parse_policy_profiles,
    validate_policy_profiles,
    validate_policy_profiles_file,
)


def _repo_config_path() -> Path:
    here = Path(__file__).resolve().parent
    return here.parents[1] / "config" / "policy-profiles.yaml"


def test_repo_policy_profiles_file_is_valid():
    path = _repo_config_path()
    if not path.is_file():
        pytest.skip("config/policy-profiles.yaml not present")
    assert validate_policy_profiles_file(path) is True


def test_valid_minimal_profile_document():
    data = {
        "version": 1,
        "profiles": [
            {
                "profile_id": "prof-test",
                "scope": "repo",
                "scope_id": "gateway",
            }
        ],
    }
    assert validate_policy_profiles(data) == []
    profiles = parse_policy_profiles(data)
    assert len(profiles) == 1
    assert profiles[0].profile_id == "prof-test"


def test_missing_version_rejected():
    data = {"profiles": []}
    errors = validate_policy_profiles(data)
    assert any("version" in err for err in errors)


def test_duplicate_scope_binding_rejected():
    data = {
        "version": 1,
        "profiles": [
            {"profile_id": "a", "scope": "repo", "scope_id": "gateway"},
            {"profile_id": "b", "scope": "repo", "scope_id": "gateway"},
        ],
    }
    errors = validate_policy_profiles(data)
    assert any("duplicate scope binding" in err for err in errors)


def test_invalid_budget_threshold_rejected():
    data = {
        "version": 1,
        "profiles": [
            {
                "profile_id": "prof-bad-budget",
                "scope": "team",
                "scope_id": "eng",
                "policy_json": {"budget": {"soft_gate_threshold_pct": 150}},
            }
        ],
    }
    errors = validate_policy_profiles(data)
    assert any("budget" in err for err in errors)


def test_invalid_rate_limit_threshold_rejected():
    data = {
        "version": 1,
        "profiles": [
            {
                "profile_id": "prof-bad-rate",
                "scope": "team",
                "scope_id": "eng",
                "policy_json": {"rate_limit": {"preemptive_429_threshold": 0}},
            }
        ],
    }
    errors = validate_policy_profiles(data)
    assert any("rate_limit" in err for err in errors)


def test_invalid_mcp_mode_rejected():
    data = {
        "version": 1,
        "profiles": [
            {
                "profile_id": "prof-bad-mcp",
                "scope": "workspace",
                "scope_id": "core",
                "policy_json": {"mcp": {"mode": "block-all", "servers": []}},
            }
        ],
    }
    errors = validate_policy_profiles(data)
    assert any("mcp" in err for err in errors)


def test_load_invalid_yaml_returns_errors(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("profiles:\n  - profile_id: : : :\n")
    data, errors = load_policy_profiles_file(bad)
    assert data is None
    assert errors
