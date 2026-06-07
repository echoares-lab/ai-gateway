"""Unit tests for workspace team budget rules (P0-4)."""

from pathlib import Path

from workspace_rules import load_workspace_rules, resolve_team_budget, tenancy_team_alias


def test_tenancy_team_alias():
    assert tenancy_team_alias("echoares", "core", "eng") == "echoares-core-eng"


def test_resolve_team_budget_merges_defaults_and_overrides():
    rules = {
        "defaults": {"max_budget": 50.0, "rpm_limit": 30, "tpm_limit": 10000, "budget_duration": "1d"},
        "teams": {"echoares-core-eng": {"max_budget": 500.0, "rpm_limit": 120}},
    }
    budget = resolve_team_budget("echoares-core-eng", rules)
    assert budget["max_budget"] == 500.0
    assert budget["rpm_limit"] == 120
    assert budget["tpm_limit"] == 10000
    assert budget["budget_duration"] == "1d"


def test_resolve_team_budget_unknown_team_uses_defaults():
    rules = {"defaults": {"max_budget": 25.0, "rpm_limit": 10}}
    budget = resolve_team_budget("unknown-team", rules)
    assert budget == {"max_budget": 25.0, "rpm_limit": 10}


def test_load_workspace_rules_from_repo_config():
    here = Path(__file__).resolve().parent
    candidates = [here.parents[2] / "config" / "workspace-rules.yaml"] if len(here.parents) > 2 else []
    rules_path = next((p for p in candidates if p.is_file()), None)
    if rules_path is None:
        return
    rules = load_workspace_rules(rules_path)
    assert "defaults" in rules
    assert "teams" in rules
    assert "echoares-core-eng" in rules["teams"]


def test_load_workspace_rules_tmp_file(tmp_path):
    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text("defaults:\n  max_budget: 10\n")
    rules = load_workspace_rules(rules_file)
    assert rules["defaults"]["max_budget"] == 10
