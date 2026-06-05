"""Policy engine service (Epic #38).

Evaluates RoutingContext and returns RoutingDecision. Phase 2 evaluators:
repo affinity (38-5), rate-limit aggregation (38-7), budget gates (38-9),
agent affinity (38-6).
"""

from __future__ import annotations

import os
from functools import lru_cache

from evaluator.agent_affinity import apply_agent_affinity
from evaluator.budget import apply_budget_gates
from evaluator.credential_events import handle_credential_event
from evaluator.fallback import evaluate_fallback_layers
from evaluator.repo_affinity import apply_repo_affinity
from fastapi import Depends, FastAPI, HTTPException
from profile_store import ProfileStore
from redis_store import RedisStateStore
from schemas import (
    CredentialEvent,
    CredentialEventResponse,
    EvaluateRequest,
    EvaluateResponse,
    HealthResponse,
    PolicyProfile,
    PolicyScope,
    RoutingDecision,
)

app = FastAPI(title="Policy Engine", version="0.1.0")

POLICY_VERSION = os.environ.get("POLICY_VERSION", "v0-stub")
DEFAULT_FALLBACK_BASELINE = os.environ.get(
    "POLICY_DEFAULT_FALLBACK_BASELINE",
    "litellm-config.yaml",
)
PREEMPTIVE_429_THRESHOLD = int(os.environ.get("POLICY_PREEMPTIVE_429_THRESHOLD", "3"))


@lru_cache
def get_redis_store() -> RedisStateStore:
    return RedisStateStore.from_env()


@lru_cache
def get_profile_store() -> ProfileStore:
    return ProfileStore.from_env()


def _quota_aware_stubs(context: EvaluateRequest) -> tuple[list[str], bool, list[str]]:
    """Phase 1 stub for quota-aware deprioritization (full logic in 38-7 / 38-9)."""
    deprioritized: list[str] = []
    rules: list[str] = []

    for snapshot in context.context.rate_limits:
        if snapshot.in_cooldown and snapshot.credential_id:
            deprioritized.append(snapshot.credential_id)
            rules.append("rate_limit:cooldown_skip")
        if (
            snapshot.rolling_429_count_5m >= PREEMPTIVE_429_THRESHOLD or snapshot.pre_emptive_degraded
        ) and snapshot.credential_id:
            if snapshot.credential_id not in deprioritized:
                deprioritized.append(snapshot.credential_id)
            rules.append("rate_limit:preemptive_deprioritize")

    quota_aware = context.context.pool_affinity_mode == "quota-aware" or bool(deprioritized)
    if context.context.pool_affinity_mode == "quota-aware":
        rules.append("pool:quota_aware_mode")

    return deprioritized, quota_aware, rules


def evaluate(
    context: EvaluateRequest,
    *,
    store: RedisStateStore | None = None,
    profile_store: ProfileStore | None = None,
) -> RoutingDecision:
    """Evaluator — repo affinity profiles + quota-aware contract stubs."""
    redis_store = store if store is not None else get_redis_store()
    profiles_db = profile_store if profile_store is not None else get_profile_store()
    merged_context = redis_store.merge_rate_limits_from_redis(context.context)
    context = context.model_copy(update={"context": merged_context})

    model = context.context.requested_model
    rules: list[str] = []
    if redis_store.enabled:
        rules.append("redis:rate_limits_merged")

    if context.context.dry_run:
        rules.append("dry_run:no_state_write")

    profiles = profiles_db.get_profiles_for_tenancy(
        context.context.tenancy,
        redis_store=redis_store,
        cache_write=not context.context.dry_run,
    )
    allowed, fallback, tier_pref, affinity_rules = apply_repo_affinity(model, profiles)
    rules.extend(affinity_rules)
    if not affinity_rules:
        rules.append("stub:pass_through")
    if profiles_db.enabled and profiles:
        rules.append("postgres:profiles_loaded")

    budget_result = apply_budget_gates(context.context, profiles)
    rules.extend(budget_result.rules_applied or [])
    if budget_result.credential_tier_preference:
        tier_pref = budget_result.credential_tier_preference

    deprioritized, quota_aware, quota_rules = _quota_aware_stubs(context)
    rules.extend(quota_rules)
    for cred_id in budget_result.deprioritized_credentials or []:
        if cred_id not in deprioritized:
            deprioritized.append(cred_id)
    if deprioritized:
        quota_aware = True

    gate = budget_result.gate
    deny_reason = budget_result.deny_reason
    retry_after = budget_result.retry_after_seconds

    preferred_cred, session_key, lock_family, cache_cold_start, tier_pref, agent_rules = apply_agent_affinity(
        context.context,
        redis_store,
        deprioritized_credentials=deprioritized,
        tier_preference=tier_pref,
        dry_run=context.context.dry_run,
    )
    rules.extend(agent_rules)

    agent_affinity: dict | None = None
    if context.context.agent_id and redis_store.enabled:
        agent_affinity = redis_store.get_agent_affinity(context.context.agent_id)

    health_scores = context.context.metadata.get("health_scores")
    if not isinstance(health_scores, dict):
        health_scores = {}

    deployment_credentials = context.context.metadata.get("deployment_credentials")
    if not isinstance(deployment_credentials, dict):
        deployment_credentials = context.context.metadata.get("backing_credentials")
    if not isinstance(deployment_credentials, dict):
        deployment_credentials = {}

    fallback_result = evaluate_fallback_layers(
        model,
        allowed_models=allowed,
        policy_fallback=fallback,
        capabilities=context.context.capabilities,
        budget=context.context.budget,
        rate_limits=context.context.rate_limits,
        deprioritized_credentials=deprioritized,
        agent_affinity=agent_affinity,
        health_scores=health_scores,
        deployment_credentials=deployment_credentials,
        policy_profiles=profiles,
        baseline_path=DEFAULT_FALLBACK_BASELINE,
        tier_preference=tier_pref,
    )
    rules.extend(fallback_result.rules_applied)

    debug: dict = {"baseline": DEFAULT_FALLBACK_BASELINE, **fallback_result.debug}
    if profiles:
        debug["policy_profiles"] = [profile.profile_id for profile in profiles]
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
        policy_version=POLICY_VERSION,
        rules_applied=rules,
        debug=debug,
    )


@app.get("/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(policy_version=POLICY_VERSION)


@app.post("/v1/evaluate", response_model=EvaluateResponse)
def evaluate_route(body: EvaluateRequest) -> EvaluateResponse:
    if not body.context.requested_model:
        raise HTTPException(status_code=422, detail="requested_model is required")
    return EvaluateResponse(decision=evaluate(body))


@app.post(
    "/v1/events/credential",
    status_code=202,
    response_model=CredentialEventResponse,
)
def credential_event_route(
    body: CredentialEvent,
    store: RedisStateStore = Depends(get_redis_store),
) -> CredentialEventResponse:
    """Accept credential-prober transitions and update Redis cooldown registry."""
    handle_credential_event(body, store)
    return CredentialEventResponse(accepted=True)


@app.get("/v1/profiles/{scope}/{scope_id}", response_model=PolicyProfile)
def get_policy_profile(
    scope: PolicyScope,
    scope_id: str,
    profile_store: ProfileStore = Depends(get_profile_store),
) -> PolicyProfile:
    profile = profile_store.get_profile(scope, scope_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Policy profile not found")
    return profile
