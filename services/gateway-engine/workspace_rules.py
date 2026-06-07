"""Load workspace team budget/rate-limit rules for LiteLLM provisioning (P0-4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_BUDGET_FIELDS = ("max_budget", "budget_duration", "rpm_limit", "tpm_limit")


def _default_rules_path() -> Path:
    here = Path(__file__).resolve().parent
    candidates = [
        here.parents[2] / "config" / "workspace-rules.yaml",
        here / "config" / "workspace-rules.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def load_workspace_rules(path: str | Path | None = None) -> dict[str, Any]:
    """Parse workspace-rules YAML; returns empty dict on missing/invalid file."""
    rules_path = Path(path) if path else _default_rules_path()
    if not rules_path.is_file():
        return {}
    try:
        data = yaml.safe_load(rules_path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_team_budget(team_alias: str, rules: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge defaults with per-team overrides for LiteLLM team budget fields."""
    cfg = rules if rules is not None else load_workspace_rules()
    merged: dict[str, Any] = {}
    defaults = cfg.get("defaults")
    if isinstance(defaults, dict):
        for field in _BUDGET_FIELDS:
            if field in defaults and defaults[field] is not None:
                merged[field] = defaults[field]

    teams = cfg.get("teams")
    if isinstance(teams, dict):
        overrides = teams.get(team_alias)
        if isinstance(overrides, dict):
            for field in _BUDGET_FIELDS:
                if field in overrides and overrides[field] is not None:
                    merged[field] = overrides[field]
    return merged


def tenancy_team_alias(org: str, workspace: str, team: str) -> str:
    """Build canonical team slug per docs/TENANCY.md §2.1."""
    return f"{org}-{workspace}-{team}"
