"""Offline validation for git-tracked policy profile promotion (P0-7, Epic #35)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from schemas import PolicyProfile, PolicyScope


class BudgetPolicyConfig(BaseModel):
    soft_gate_threshold_pct: float | None = Field(default=None, ge=0, le=100)
    cost_tier_threshold_pct: float | None = Field(default=None, ge=0, le=100)
    cost_tier_preference: str | None = None
    hard_gate_enabled: bool | None = None


class RateLimitPolicyConfig(BaseModel):
    preemptive_429_threshold: int = Field(ge=1)


class McpPolicyConfig(BaseModel):
    mode: Literal["allowlist", "denylist"] = "denylist"
    servers: list[str] = Field(default_factory=list)

    @field_validator("servers")
    @classmethod
    def servers_are_strings(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned


def _default_profiles_path() -> Path:
    here = Path(__file__).resolve().parent
    repo_root = here.parents[1]
    candidates = [
        repo_root / "config" / "policy-profiles.yaml",
        here / "config" / "policy-profiles.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def load_policy_profiles_file(path: str | Path | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """Load policy-profiles YAML. Returns (data, errors)."""
    profiles_path = Path(path) if path else _default_profiles_path()
    errors: list[str] = []

    try:
        raw = profiles_path.read_text()
    except OSError as exc:
        return None, [f"cannot read {profiles_path}: {exc}"]

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, [f"YAML syntax error in {profiles_path}: {exc}"]

    if data is None:
        return None, [f"{profiles_path}: file is empty"]
    if not isinstance(data, dict):
        return None, [f"{profiles_path}: root must be a YAML mapping"]
    return data, errors


def _validate_policy_json(profile_id: str, policy_json: Any) -> list[str]:
    errors: list[str] = []
    prefix = f"profile {profile_id!r} policy_json"

    if policy_json is None:
        return errors
    if not isinstance(policy_json, dict):
        return [f"{prefix} must be an object"]

    budget = policy_json.get("budget")
    if budget is not None:
        try:
            BudgetPolicyConfig.model_validate(budget)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(part) for part in err["loc"])
                errors.append(f"{prefix}.budget.{loc}: {err['msg']}")

    rate_limit = policy_json.get("rate_limit")
    if rate_limit is not None:
        try:
            RateLimitPolicyConfig.model_validate(rate_limit)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(part) for part in err["loc"])
                errors.append(f"{prefix}.rate_limit.{loc}: {err['msg']}")

    mcp = policy_json.get("mcp")
    if mcp is not None:
        try:
            McpPolicyConfig.model_validate(mcp)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(part) for part in err["loc"])
                errors.append(f"{prefix}.mcp.{loc}: {err['msg']}")

    legacy_allowlist = policy_json.get("mcp_allowlist")
    if legacy_allowlist is not None and not isinstance(legacy_allowlist, list):
        errors.append(f"{prefix}.mcp_allowlist must be a list")
    elif isinstance(legacy_allowlist, list) and not all(isinstance(item, str) for item in legacy_allowlist):
        errors.append(f"{prefix}.mcp_allowlist entries must be strings")

    cross_family = policy_json.get("allow_cross_family_fallback")
    if cross_family is not None and not isinstance(cross_family, bool):
        errors.append(f"{prefix}.allow_cross_family_fallback must be a boolean")

    return errors


def validate_policy_profiles(data: dict[str, Any]) -> list[str]:
    """Validate policy-profiles document structure and profile rows."""
    errors: list[str] = []

    version = data.get("version")
    if version is None:
        errors.append("missing required key 'version'")
    elif not isinstance(version, int) or version < 1:
        errors.append(f"version must be a positive integer, got {version!r}")

    profiles = data.get("profiles")
    if profiles is None:
        errors.append("missing required key 'profiles'")
        return errors
    if not isinstance(profiles, list):
        errors.append(f"profiles must be a list, got {type(profiles).__name__}")
        return errors

    seen_profile_ids: set[str] = set()
    seen_scope_pairs: set[tuple[str, str]] = set()

    for idx, raw_profile in enumerate(profiles):
        prefix = f"profiles[{idx}]"
        if not isinstance(raw_profile, dict):
            errors.append(f"{prefix} must be an object")
            continue

        try:
            profile = PolicyProfile.model_validate(raw_profile)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(part) for part in err["loc"])
                errors.append(f"{prefix}.{loc}: {err['msg']}")
            continue

        if profile.profile_id in seen_profile_ids:
            errors.append(f"duplicate profile_id {profile.profile_id!r}")
        seen_profile_ids.add(profile.profile_id)

        scope_key = (profile.scope.value, profile.scope_id)
        if scope_key in seen_scope_pairs:
            errors.append(
                f"duplicate scope binding ({profile.scope.value}, {profile.scope_id!r})"
            )
        seen_scope_pairs.add(scope_key)

        if profile.scope == PolicyScope.ORG and not profile.scope_id:
            errors.append(f"{prefix}: org scope requires non-empty scope_id")

        errors.extend(_validate_policy_json(profile.profile_id, profile.policy_json))

    return errors


def parse_policy_profiles(data: dict[str, Any]) -> list[PolicyProfile]:
    """Parse validated profiles document into PolicyProfile models."""
    errors = validate_policy_profiles(data)
    if errors:
        raise ValueError("\n".join(errors))
    profiles = data.get("profiles") or []
    return [PolicyProfile.model_validate(item) for item in profiles]


def validate_policy_profiles_file(path: str | Path | None = None) -> bool:
    """Return True when the policy-profiles file passes pre-flight validation."""
    data, load_errors = load_policy_profiles_file(path)
    if load_errors:
        return False
    assert data is not None
    return not validate_policy_profiles(data)
