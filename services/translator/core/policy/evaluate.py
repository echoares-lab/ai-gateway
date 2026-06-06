"""In-process policy evaluation orchestrator (Epic 2, issue #181)."""

from __future__ import annotations

import asyncio
import os
from functools import lru_cache

from core.policy.agent_affinity import apply_agent_affinity
from core.policy.budget import apply_budget_gates
from core.policy.credential_events import handle_credential_event
from core.policy.fallback import evaluate_fallback_layers
from core.policy.inventory_store import InventoryStore
from core.policy.mcp_visibility import resolve_mcp_visibility
from core.policy.profile_store import ProfileStore
from core.policy.rate_limit import aggregate_and_evaluate
from core.policy.redis_store import RedisStateStore
from core.policy.repo_affinity import apply_repo_affinity
from core.policy.schemas import (
    CredentialEvent,
    EvaluateRequest,
    RoutingDecision,
)

POLICY_VERSION = os.environ.get("POLICY_VERSION", "v0-stub")
DEFAULT_FALLBACK_BASELINE = os.environ.get(
    "POLICY_DEFAULT_FALLBACK_BASELINE",
    "litellm-config.yaml",
)


@lru_cache
def get_redis_store() -> RedisStateStore:
    return RedisStateStore.from_env()


@lru_cache
def get_profile_store() -> ProfileStore:
    return ProfileStore.from_env()


@lru_cache
def get_inventory_store() -> InventoryStore:
    return InventoryStore.from_env()


def _filter_degraded_models(
    models: list[str],
    skipped: list[str],
) -> list[str]:
    if not skipped:
        return models
    skip_set = set(skipped)
    return [model for model in models if model not in skip_set]


def _merge_deprioritized(
    *groups: list[str] | None,
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not group:
            continue
        for cred_id in group:
            if cred_id not in seen:
                seen.add(cred_id)
                merged.append(cred_id)
    return merged


def evaluate(
    context: EvaluateRequest,
    *,
    store: RedisStateStore | None = None,
    profile_store: ProfileStore | None = None,
    inventory_store: InventoryStore | None = None,
) -> RoutingDecision:
    """Evaluate routing policy for a single request (synchronous)."""
    redis_store = store if store is not None else get_redis_store()
    profiles_db = profile_store if profile_store is not None else get_profile_store()
    inventory = inventory_store if inventory_store is not None else get_inventory_store()

    model = context.context.requested_model
    rules: list[str] = []

    if context.context.dry_run:
        rules.append("dry_run:no_state_write")

    profiles = profiles_db.get_profiles_for_tenancy(
        context.context.tenancy,
        redis_store=redis_store,
        cache_write=not context.context.dry_run,
    )
    if profiles_db.enabled and profiles:
        rules.append("postgres:profiles_loaded")

    merged_context, rate_eval, merge_rules = aggregate_and_evaluate(
        context.context,
        redis_store=redis_store,
        inventory_store=inventory,
        profiles=profiles,
    )
    rules.extend(merge_rules)
    rules.extend(rate_eval.rules_applied)

    allowed, fallback, tier_pref, affinity_rules = apply_repo_affinity(model, profiles)
    rules.extend(affinity_rules)
    if not affinity_rules:
        rules.append("stub:pass_through")

    registered_mcp = merged_context.metadata.get("registered_mcp_servers")
    mcp_result = resolve_mcp_visibility(
        profiles,
        registered_mcp_servers=registered_mcp,
    )
    rules.extend(mcp_result.rules_applied)

    if rate_eval.skipped_models:
        allowed = _filter_degraded_models(allowed, rate_eval.skipped_models)
        fallback = _filter_degraded_models(fallback, rate_eval.skipped_models)

    budget_result = apply_budget_gates(merged_context, profiles)
    rules.extend(budget_result.rules_applied or [])
    if budget_result.credential_tier_preference:
        tier_pref = budget_result.credential_tier_preference

    deprioritized = _merge_deprioritized(
        rate_eval.deprioritized_credentials,
        budget_result.deprioritized_credentials,
    )
    quota_aware = rate_eval.quota_aware_mode or bool(deprioritized)

    gate = budget_result.gate
    deny_reason = budget_result.deny_reason
    retry_after = budget_result.retry_after_seconds

    preferred_cred, session_key, lock_family, cache_cold_start, tier_pref, agent_rules = apply_agent_affinity(
        merged_context,
        redis_store,
        deprioritized_credentials=deprioritized,
        tier_preference=tier_pref,
        dry_run=context.context.dry_run,
    )
    rules.extend(agent_rules)

    agent_affinity: dict | None = None
    if context.context.agent_id and redis_store.enabled:
        agent_affinity = redis_store.get_agent_affinity(context.context.agent_id)

    health_scores = merged_context.metadata.get("health_scores")
    if not isinstance(health_scores, dict):
        health_scores = {}

    deployment_credentials = merged_context.metadata.get("deployment_credentials")
    if not isinstance(deployment_credentials, dict):
        deployment_credentials = merged_context.metadata.get("backing_credentials")
    if not isinstance(deployment_credentials, dict):
        deployment_credentials = {}

    fallback_result = evaluate_fallback_layers(
        model,
        allowed_models=allowed,
        policy_fallback=fallback,
        capabilities=merged_context.capabilities,
        budget=merged_context.budget,
        rate_limits=merged_context.rate_limits,
        deprioritized_credentials=deprioritized,
        agent_affinity=agent_affinity,
        health_scores=health_scores,
        deployment_credentials=deployment_credentials,
        policy_profiles=profiles,
        baseline_path=DEFAULT_FALLBACK_BASELINE,
        tier_preference=tier_pref,
        request_metadata=merged_context.metadata,
    )
    rules.extend(fallback_result.rules_applied)

    debug: dict = {"baseline": DEFAULT_FALLBACK_BASELINE, **fallback_result.debug}
    if profiles:
        debug["policy_profiles"] = [profile.profile_id for profile in profiles]
    if rate_eval.merged_rate_limits:
        debug["rate_limits"] = [snap.model_dump(mode="json") for snap in rate_eval.merged_rate_limits]
    if rate_eval.skipped_models:
        debug["skipped_models_all_cooled"] = rate_eval.skipped_models
    if agent_affinity:
        debug["agent_affinity"] = agent_affinity

    return RoutingDecision(
        gate=gate,
        deny_reason=deny_reason,
        retry_after_seconds=retry_after,
        allowed_models=allowed,
        fallback_chain=fallback_result.fallback_chain,
        ordered_deployments=fallback_result.ordered_deployments,
        credential_tier_preference=tier_pref,
        preferred_credential_id=preferred_cred,
        session_key=session_key,
        lock_model_family=lock_family or fallback_result.lock_model_family,
        cache_cold_start=cache_cold_start,
        quota_aware_mode=quota_aware,
        deprioritized_credentials=deprioritized,
        allowed_mcp_servers=mcp_result.allowed_mcp_servers,
        denied_mcp_servers=mcp_result.denied_mcp_servers,
        policy_version=POLICY_VERSION,
        rules_applied=rules,
        debug=debug,
    )


async def evaluate_async(
    context: EvaluateRequest,
    *,
    store: RedisStateStore | None = None,
    profile_store: ProfileStore | None = None,
    inventory_store: InventoryStore | None = None,
) -> RoutingDecision:
    """Async entry point for policy evaluation (runs sync logic in a thread pool)."""
    return await asyncio.to_thread(
        evaluate,
        context,
        store=store,
        profile_store=profile_store,
        inventory_store=inventory_store,
    )


def process_credential_event(
    event: CredentialEvent,
    store: RedisStateStore | None = None,
) -> bool:
    """Apply credential transition to Redis cooldown registry."""
    redis_store = store if store is not None else get_redis_store()
    return handle_credential_event(event, redis_store)


async def process_credential_event_async(
    event: CredentialEvent,
    store: RedisStateStore | None = None,
) -> bool:
    """Async wrapper for credential event handling."""
    return await asyncio.to_thread(process_credential_event, event, store=store)
