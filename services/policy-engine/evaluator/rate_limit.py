"""Rate-limit state aggregator — merge translator, inventory, Redis (38-7)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from schemas import PolicyProfile, RateLimitSnapshot, RoutingContext

if TYPE_CHECKING:
    from inventory_store import InventoryStore
    from redis_store import RedisStateStore

DEFAULT_PREEMPTIVE_429_THRESHOLD = int(os.environ.get("POLICY_PREEMPTIVE_429_THRESHOLD", "3"))


@dataclass(frozen=True)
class RateLimitEvaluation:
    """Deprioritization output from aggregated rate-limit state."""

    deprioritized_credentials: list[str]
    quota_aware_mode: bool
    rules_applied: list[str]
    merged_rate_limits: list[RateLimitSnapshot]
    skipped_models: list[str]


def _cred_key(snapshot: RateLimitSnapshot) -> tuple[str | None, str | None]:
    return (snapshot.provider, snapshot.credential_id)


def _merge_snapshots(
    existing: RateLimitSnapshot | None,
    incoming: RateLimitSnapshot,
) -> RateLimitSnapshot:
    if existing is None:
        return incoming
    cooldown_until = existing.cooldown_until
    if incoming.cooldown_until and (cooldown_until is None or incoming.cooldown_until > cooldown_until):
        cooldown_until = incoming.cooldown_until
    in_cooldown = existing.in_cooldown or incoming.in_cooldown
    if cooldown_until:
        now = datetime.now(timezone.utc)
        in_cooldown = in_cooldown or cooldown_until > now
    pre_emptive = existing.pre_emptive_degraded or incoming.pre_emptive_degraded
    return RateLimitSnapshot(
        provider=incoming.provider or existing.provider,
        credential_id=incoming.credential_id or existing.credential_id,
        in_cooldown=in_cooldown,
        cooldown_until=cooldown_until,
        rolling_429_count_5m=max(
            existing.rolling_429_count_5m,
            incoming.rolling_429_count_5m,
        ),
        pre_emptive_degraded=pre_emptive,
    )


def _collect_credential_ids(context: RoutingContext) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for snap in context.rate_limits:
        if snap.credential_id and snap.credential_id not in seen:
            seen.add(snap.credential_id)
            ids.append(snap.credential_id)
    for creds in deployment_credentials_from_metadata(context).values():
        for cred in creds:
            if cred not in seen:
                seen.add(cred)
                ids.append(cred)
    return ids


def _credential_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
    return out


def _merge_credential_map(target: dict[str, list[str]], source: Any) -> None:
    if not isinstance(source, dict):
        return
    for model, creds in source.items():
        if not isinstance(model, str) or not model:
            continue
        cred_ids = _credential_list(creds)
        if cred_ids:
            target[model] = cred_ids


def deployment_credentials_from_metadata(context: RoutingContext) -> dict[str, list[str]]:
    """Return explicit deployment -> credential ids mapping; unknown mapping stays empty."""
    deployment_credentials: dict[str, list[str]] = {}
    _merge_credential_map(deployment_credentials, context.metadata.get("backing_credentials"))
    _merge_credential_map(deployment_credentials, context.metadata.get("deployment_credentials"))

    registry = context.metadata.get("model_registry")
    if isinstance(registry, dict):
        registry_creds = _credential_list(registry.get("deployment_credentials") or registry.get("backing_credentials"))
        if registry_creds:
            for model in (
                registry.get("canonical_model_id"),
                context.requested_model,
                context.requested_model.replace(".", "-"),
            ):
                if isinstance(model, str) and model:
                    deployment_credentials.setdefault(model, registry_creds)

    return deployment_credentials


def merge_rate_limit_sources(
    context: RoutingContext,
    *,
    redis_store: RedisStateStore | None = None,
    inventory_store: InventoryStore | None = None,
) -> tuple[RoutingContext, list[str]]:
    """Merge translator #59 signals, inventory cooldowns, and Redis rolling counts."""
    rules: list[str] = []
    by_cred: dict[tuple[str | None, str | None], RateLimitSnapshot] = {}

    for snap in context.rate_limits:
        by_cred[_cred_key(snap)] = snap
    if context.rate_limits:
        rules.append("rate_limit:translator_signals_merged")

    credential_ids = _collect_credential_ids(context)
    if inventory_store is not None and inventory_store.enabled and credential_ids:
        inventory_snaps = inventory_store.routing_snapshots(credential_ids)
        for snap in inventory_snaps:
            key = _cred_key(snap)
            by_cred[key] = _merge_snapshots(by_cred.get(key), snap)
        if inventory_snaps:
            rules.append("rate_limit:inventory_routing_merged")
        if any(s.in_cooldown for s in inventory_snaps):
            rules.append("rate_limit:inventory_status_excluded")

    merged_list = list(by_cred.values())
    merged_context = context.model_copy(update={"rate_limits": merged_list})

    if redis_store is not None and redis_store.enabled:
        merged_context = redis_store.merge_rate_limits_from_redis(merged_context)
        rules.append("redis:rate_limits_merged")

    return merged_context, rules


def resolve_preemptive_threshold(
    profiles: list[PolicyProfile],
    default: int = DEFAULT_PREEMPTIVE_429_THRESHOLD,
) -> int:
    """Most-specific policy profile may override rolling 429 threshold."""
    for profile in reversed(profiles):
        rate_cfg = profile.policy_json.get("rate_limit")
        if isinstance(rate_cfg, dict):
            raw = rate_cfg.get("preemptive_429_threshold")
            if raw is not None:
                try:
                    return max(int(raw), 1)
                except (TypeError, ValueError):
                    continue
    return default


def _all_credentials_degraded(
    credential_ids: list[str],
    deprioritized: set[str],
    snapshots: dict[str, RateLimitSnapshot],
) -> bool:
    if not credential_ids:
        return False
    for cred_id in credential_ids:
        if cred_id not in deprioritized:
            snap = snapshots.get(cred_id)
            if snap is None or (not snap.in_cooldown and not snap.pre_emptive_degraded):
                return False
    return True


def evaluate_rate_limits(
    context: RoutingContext,
    *,
    profiles: list[PolicyProfile] | None = None,
    threshold: int | None = None,
) -> RateLimitEvaluation:
    """Apply pre-emptive deprioritization and quota-aware mode from merged state."""
    profiles = profiles or []
    effective_threshold = threshold if threshold is not None else resolve_preemptive_threshold(profiles)

    deprioritized: list[str] = []
    deprioritized_set: set[str] = set()
    rules: list[str] = []
    snapshots_by_cred: dict[str, RateLimitSnapshot] = {}

    for snap in context.rate_limits:
        if snap.credential_id:
            snapshots_by_cred[snap.credential_id] = snap

    for snap in context.rate_limits:
        cred_id = snap.credential_id
        if not cred_id:
            continue

        if snap.in_cooldown:
            if cred_id not in deprioritized_set:
                deprioritized.append(cred_id)
                deprioritized_set.add(cred_id)
            rules.append("rate_limit:cooldown_skip")

        preemptive = snap.rolling_429_count_5m >= effective_threshold or snap.pre_emptive_degraded
        if preemptive:
            snap = snap.model_copy(update={"pre_emptive_degraded": True})
            snapshots_by_cred[cred_id] = snap
            if cred_id not in deprioritized_set:
                deprioritized.append(cred_id)
                deprioritized_set.add(cred_id)
            if "rate_limit:preemptive_deprioritize" not in rules:
                rules.append("rate_limit:preemptive_deprioritize")

    quota_aware = context.pool_affinity_mode == "quota-aware"
    if context.pool_affinity_mode == "quota-aware":
        rules.append("pool:quota_aware_mode")
    elif deprioritized:
        quota_aware = True

    skipped_models: list[str] = []
    backing = deployment_credentials_from_metadata(context)
    for model, creds in backing.items():
        if _all_credentials_degraded(creds, deprioritized_set, snapshots_by_cred):
            skipped_models.append(model)
    if skipped_models:
        rules.append("rate_limit:skip_all_cooled_models")

    merged = list(snapshots_by_cred.values())
    for snap in context.rate_limits:
        if snap.credential_id and snap.credential_id not in snapshots_by_cred:
            merged.append(snap)

    return RateLimitEvaluation(
        deprioritized_credentials=deprioritized,
        quota_aware_mode=quota_aware,
        rules_applied=rules,
        merged_rate_limits=merged,
        skipped_models=skipped_models,
    )


def aggregate_and_evaluate(
    context: RoutingContext,
    *,
    redis_store: RedisStateStore | None = None,
    inventory_store: InventoryStore | None = None,
    profiles: list[PolicyProfile] | None = None,
    threshold: int | None = None,
) -> tuple[RoutingContext, RateLimitEvaluation, list[str]]:
    """Full 38-7 pipeline: merge sources then evaluate deprioritization."""
    merged_context, merge_rules = merge_rate_limit_sources(
        context,
        redis_store=redis_store,
        inventory_store=inventory_store,
    )
    evaluation = evaluate_rate_limits(
        merged_context,
        profiles=profiles,
        threshold=threshold,
    )
    return merged_context, evaluation, merge_rules
