"""Layered fallback rule evaluator (Epic #38, issue 38-8).

Evaluates fallback ordering per POLICY_ENGINE_AND_ROUTING_REFACTOR.md §5.5:
  1. Capability hard filter
  2. Policy allowlist
  3. Affinity family lock
  4. Rate-limit cooldown skip
  5. Health-weighted order
  5b. Eval-quality reorder (optional, policy_json.eval)
  6. Cost tier preference (budget pressure)
  7. Static YAML baseline safety net
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.policy.quality import apply_quality_reorder, extract_eval_config, resolve_task_category
from core.policy.schemas import (
    BudgetSnapshot,
    PolicyProfile,
    RateLimitSnapshot,
    RequestCapabilities,
)
from core.model_registry import ModelRegistryStore

logger = logging.getLogger(__name__)

BUDGET_COST_TIER_THRESHOLD_PCT = float(os.environ.get("POLICY_BUDGET_COST_TIER_THRESHOLD_PCT", "80"))

_registry_store = ModelRegistryStore()

# Minimal safety net if DB is empty and YAML load fails.
_EMBEDDED_BASELINE: dict[str, list[str]] = {
    "claude-sonnet-4-6": ["gemini-3-flash", "gemini-3-flash-via-gcli", "gpt-5-4"],
    "claude-haiku-4-5": ["gemini-3-flash", "gemini-3-flash-via-gcli", "gpt-5-4-mini"],
    "gpt-5-4": ["gemini-3-flash", "gemini-3-flash-via-gcli", "claude-sonnet-4-6"],
    "gpt-5-4-mini": ["gemini-3-flash", "gemini-3-flash-via-gcli", "claude-haiku-4-5"],
    "gemini-3-flash": ["gemini-3-flash-via-gcli", "claude-haiku-4-5", "gpt-5-4-mini"],
}


@lru_cache(maxsize=1)
def _get_cached_registry() -> dict[str, Any]:
    """Fetch all models from DB registry and cache for policy evaluation."""
    try:
        res = _registry_store.list_models()
        if res.models:
            return {m.model_id: m for m in res.models}
    except Exception as exc:
        logger.warning("Failed to load model registry from DB: %s", exc)
    return {}


@dataclass
class FallbackResult:

    ordered_deployments: list[str]
    fallback_chain: list[str]
    lock_model_family: bool = False
    rules_applied: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


def _infer_family(model: str) -> str:
    base = model.split("-at-")[0]
    if base.startswith("claude"):
        return "anthropic"
    if base.startswith("gpt") or base.startswith("codex"):
        return "openai"
    if base.startswith("gemini"):
        return "gemini"
    return "unknown"


def model_traits(model: str) -> dict[str, Any]:
    """Return capability traits for a model (registry + inference)."""
    registry = _get_cached_registry()
    if model in registry:
        record = registry[model]
        return {
            "family": record.family,
            "tools": record.supports_tools if record.supports_tools is not None else True,
            "vision": record.supports_vision if record.supports_vision is not None else False,
            "cost": record.cost_tier or 2,
        }
    family = _infer_family(model)
    cost = 1 if any(x in model for x in ("haiku", "mini", "lite", "flash")) else 2
    if any(x in model for x in ("opus", "pro-high", "gpt-5-5")):
        cost = 3
    return {
        "family": family,
        "tools": family != "unknown",
        "vision": "image" in model,
        "cost": cost,
    }


def _dedupe_preserve_order(models: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for model in models:
        if model and model not in seen:
            seen.add(model)
            out.append(model)
    return out


@lru_cache(maxsize=4)
def load_yaml_baseline(path: str) -> dict[str, list[str]]:
    """Load fallbacks from DB; fall back to YAML or embedded map."""
    registry = _get_cached_registry()
    baseline: dict[str, list[str]] = {}
    for model_id, record in registry.items():
        fallbacks = record.policy_metadata.get("fallbacks")
        if isinstance(fallbacks, list):
            baseline[model_id] = [str(m) for m in fallbacks]

    if baseline:
        return baseline

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("PyYAML unavailable; using embedded fallback baseline")
        return dict(_EMBEDDED_BASELINE)

    file_path = Path(path)
    if not file_path.is_file():
        return dict(_EMBEDDED_BASELINE)

    try:
        with file_path.open(encoding="utf-8") as handle:
            doc = yaml.safe_load(handle) or {}
    except OSError as exc:
        logger.warning("Failed to read fallback baseline %s: %s", path, exc)
        return dict(_EMBEDDED_BASELINE)

    # Try model-registry.yaml format first
    models_list = doc.get("models") or []
    if isinstance(models_list, list):
        for entry in models_list:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("model_id")
            fallbacks = entry.get("policy_metadata", {}).get("fallbacks")
            if model_id and isinstance(fallbacks, list):
                baseline[str(model_id)] = [str(m) for m in fallbacks]

    if baseline:
        return baseline

    # Fallback to litellm-config.yaml format
    fallbacks_raw = (doc.get("litellm_settings") or {}).get("fallbacks") or []
    for entry in fallbacks_raw:
        if not isinstance(entry, dict):
            continue
        for model, chain in entry.items():
            if isinstance(chain, list):
                baseline[str(model)] = [str(m) for m in chain]
    return baseline or dict(_EMBEDDED_BASELINE)


def _baseline_chain(
    requested_model: str,
    policy_fallback: list[str],
    baseline_path: str | None,
) -> list[str]:
    yaml_chain = load_yaml_baseline(baseline_path or "").get(requested_model, [])
    seed = [requested_model]
    if policy_fallback:
        seed.extend(policy_fallback)
    elif yaml_chain:
        seed.extend(yaml_chain)
    return _dedupe_preserve_order(seed)


def _policy_allows_cross_family(profiles: list[PolicyProfile]) -> bool:
    for profile in reversed(profiles):
        if profile.policy_json.get("allow_cross_family_fallback") is True:
            return True
    return False


def _unavailable_credentials(
    rate_limits: list[RateLimitSnapshot],
    deprioritized: list[str],
) -> set[str]:
    unavailable: set[str] = set(deprioritized)
    for snap in rate_limits:
        if snap.credential_id and (snap.in_cooldown or snap.pre_emptive_degraded):
            unavailable.add(snap.credential_id)
    return unavailable


def _deployment_unavailable(
    model: str,
    deployment_credentials: dict[str, list[str]],
    unavailable_creds: set[str],
) -> bool:
    creds = deployment_credentials.get(model)
    if not creds:
        return False
    return all(cred in unavailable_creds for cred in creds)


def evaluate_fallback_layers(
    requested_model: str,
    *,
    allowed_models: list[str],
    policy_fallback: list[str],
    capabilities: RequestCapabilities,
    budget: BudgetSnapshot | None = None,
    rate_limits: list[RateLimitSnapshot] | None = None,
    deprioritized_credentials: list[str] | None = None,
    agent_affinity: dict[str, Any] | None = None,
    health_scores: dict[str, float] | None = None,
    deployment_credentials: dict[str, list[str]] | None = None,
    policy_profiles: list[PolicyProfile] | None = None,
    baseline_path: str | None = None,
    tier_preference: str | None = None,
    request_metadata: dict[str, Any] | None = None,
) -> FallbackResult:
    """Apply §5.5 fallback layers and return ordered deployments."""
    profiles = policy_profiles or []
    rate_limits = rate_limits or []
    deprioritized = deprioritized_credentials or []
    health_scores = health_scores or {}
    deployment_credentials = deployment_credentials or {}
    rules: list[str] = []
    debug: dict[str, Any] = {}

    candidates = _baseline_chain(requested_model, policy_fallback, baseline_path)
    allowed_set = set(allowed_models) if allowed_models else {requested_model}
    allowed_set.add(requested_model)
    if policy_fallback:
        allowed_set.update(policy_fallback)

    # Layer 1 — capability hard filter
    if capabilities.has_tools:
        before = len(candidates)
        candidates = [m for m in candidates if model_traits(m)["tools"]]
        rules.append("fallback:capability:filter_tools")
        if len(candidates) == before and before:
            debug["capability_tools_noop"] = True
    if capabilities.has_vision:
        before = len(candidates)
        candidates = [m for m in candidates if model_traits(m)["vision"]]
        rules.append("fallback:capability:filter_vision")

    # Layer 2 — policy allowlist
    before = len(candidates)
    candidates = [m for m in candidates if m in allowed_set]
    rules.append("fallback:policy:allowlist")

    # Layer 3 — affinity family lock
    lock_family = False
    locked_family: str | None = None
    if capabilities.active_tool_chain and capabilities.has_tools:
        locked_family = capabilities.model_family
        if not locked_family and agent_affinity:
            raw = agent_affinity.get("model_family")
            if isinstance(raw, str) and raw:
                locked_family = raw
        if locked_family and not _policy_allows_cross_family(profiles):
            before = len(candidates)
            candidates = [m for m in candidates if model_traits(m)["family"] == locked_family]
            rules.append("fallback:affinity:family_lock")
            lock_family = True
            debug["locked_model_family"] = locked_family

    # Layer 4 — rate-limit cooldown skip (all backing creds unavailable)
    unavailable = _unavailable_credentials(rate_limits, deprioritized)
    if unavailable and deployment_credentials:
        before = len(candidates)
        candidates = [m for m in candidates if not _deployment_unavailable(m, deployment_credentials, unavailable)]
        if len(candidates) < before:
            rules.append("fallback:rate_limit:cooldown_skip")
        debug["unavailable_credentials"] = sorted(unavailable)

    # Layer 5 — health-weighted order (eligible tail only; keep requested first when present)
    if health_scores and len(candidates) > 1:
        head = candidates[:1] if candidates[0] == requested_model else []
        tail = candidates[len(head) :]
        if tail:
            tail.sort(key=lambda m: (-health_scores.get(m, 0.0), m))
            candidates = head + tail
            rules.append("fallback:health:weighted_order")
            debug["health_scores_used"] = {m: health_scores.get(m, 0.0) for m in tail}

    # Layer 5b — eval-quality reorder (optional; fail-open when disabled or no scores)
    eval_config = extract_eval_config(profiles)
    task_category = resolve_task_category(eval_config, request_metadata)
    quality_result = apply_quality_reorder(
        candidates,
        requested_model=requested_model,
        eval_config=eval_config,
        task_category=task_category,
        health_scores=health_scores,
    )
    if quality_result.applied:
        candidates = quality_result.candidates
        rules.extend(quality_result.rules_applied)
        debug.update(quality_result.debug)

    # Layer 6 — cost tier when budget pressure
    budget_pct = budget.team_budget_pct_used if budget else None
    if budget_pct is not None and budget_pct > BUDGET_COST_TIER_THRESHOLD_PCT and len(candidates) > 1:
        head = candidates[:1] if candidates[0] == requested_model else []
        tail = candidates[len(head) :]
        if tail:
            tail.sort(key=lambda m: (model_traits(m)["cost"], m))
            candidates = head + tail
            rules.append("fallback:budget:cost_tier")
            debug["budget_pct_used"] = budget_pct

    # Layer 7 — static YAML baseline safety net
    yaml_baseline = load_yaml_baseline(baseline_path or "")
    yaml_chain = yaml_baseline.get(requested_model, _EMBEDDED_BASELINE.get(requested_model, []))
    if yaml_chain:
        existing = set(candidates)
        for model in yaml_chain:
            if model in existing or model not in allowed_set:
                continue
            traits = model_traits(model)
            if capabilities.has_tools and not traits["tools"]:
                continue
            if capabilities.has_vision and not traits["vision"]:
                continue
            if lock_family and locked_family and traits["family"] != locked_family:
                continue
            if _deployment_unavailable(model, deployment_credentials, unavailable):
                continue
            candidates.append(model)
            existing.add(model)
        if yaml_chain:
            rules.append("fallback:baseline:yaml")
            debug["yaml_baseline_source"] = baseline_path or "embedded"

    # Tier-specific deployment name for the primary model only (38-11)
    if tier_preference and candidates:
        tier_suffix = f"-at-{tier_preference}"
        primary = candidates[0]
        if primary == requested_model and not primary.endswith(tier_suffix):
            candidates = [f"{primary}{tier_suffix}", *candidates[1:]]
            candidates = _dedupe_preserve_order(candidates)
            rules.append("fallback:tier:deployment_alias")

    if not candidates:
        candidates = [requested_model]
        rules.append("fallback:fail_open_requested")

    return FallbackResult(
        ordered_deployments=candidates,
        fallback_chain=candidates,
        lock_model_family=lock_family,
        rules_applied=rules,
        debug=debug,
    )
