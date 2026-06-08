"""Repo/team affinity evaluator — allowlists, denylists, fallback overrides (38-5)."""

from __future__ import annotations

from core.policy.schemas import PolicyProfile


def apply_repo_affinity(
    requested_model: str,
    profiles: list[PolicyProfile],
    *,
    baseline_allowed: list[str] | None = None,
    baseline_fallback: list[str] | None = None,
) -> tuple[list[str], list[str], str | None, list[str]]:
    """Apply layered policy_profiles to allowed models and fallback ordering.

    Profiles are evaluated least-specific → most-specific (org, workspace, team, repo).
    Empty allowed set after filtering fails open to requested_model baseline.
    """
    allowed = list(baseline_allowed or [requested_model])
    fallback = list(baseline_fallback or [requested_model])
    tier_preference: str | None = None
    rules: list[str] = []

    for profile in profiles:
        tag = f"repo_affinity:{profile.scope.value}:{profile.scope_id}"

        if profile.denied_models:
            denied = set(profile.denied_models)
            allowed = [model for model in allowed if model not in denied]
            rules.append(f"{tag}:denylist")

        if profile.allowed_models:
            allow_set = set(profile.allowed_models)
            if allowed:
                allowed = [model for model in allowed if model in allow_set]
            else:
                allowed = list(profile.allowed_models)
            rules.append(f"{tag}:allowlist")

        if profile.fallback_chain_override:
            fallback = list(profile.fallback_chain_override)
            rules.append(f"{tag}:fallback_override")

        if profile.credential_tier_preference:
            tier_preference = profile.credential_tier_preference
            rules.append(f"{tag}:tier_preference")

    if not allowed:
        allowed = [requested_model]
        rules.append("repo_affinity:fail_open_baseline")

    return allowed, fallback, tier_preference, rules
