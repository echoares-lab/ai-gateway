"""Agent affinity evaluator — sticky credentials, family lock, rebind on 429 (38-6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from schemas import RoutingContext

if TYPE_CHECKING:
    from redis_store import RedisStateStore

BACKGROUND_TIER = "antigravity"
INTERACTIVE_TIER = "native"


def build_session_key(context: RoutingContext) -> str | None:
    """Stable CLIProxy session key from agent/session identifiers."""
    if not context.agent_id:
        return None
    if context.session_id:
        return f"agent:{context.agent_id}:{context.session_id}"
    return f"agent:{context.agent_id}"


def should_lock_model_family(context: RoutingContext) -> bool:
    caps = context.capabilities
    return bool(caps.has_tools and caps.active_tool_chain)


def _bound_credential_in_cooldown(credential_id: str, context: RoutingContext) -> bool:
    for snap in context.rate_limits:
        if snap.credential_id == credential_id and snap.in_cooldown:
            return True
    return False


def _pick_credential(context: RoutingContext, deprioritized: list[str]) -> str | None:
    meta = context.metadata
    candidates: list[str] = []
    if cid := meta.get("credential_id"):
        candidates.append(str(cid))
    raw = meta.get("credential_candidates")
    if isinstance(raw, list):
        candidates.extend(str(c) for c in raw)
    seen: set[str] = set()
    for cred in candidates:
        if cred in seen:
            continue
        seen.add(cred)
        if cred not in deprioritized:
            return cred
    return None


def _resolve_model_family(context: RoutingContext) -> str | None:
    if context.capabilities.model_family:
        return context.capabilities.model_family
    raw = context.metadata.get("model_family")
    return str(raw) if isinstance(raw, str) and raw else None


def _agent_pool_tier(context: RoutingContext) -> tuple[str | None, str | None]:
    """Background agents use lower tier; interactive agents prefer premium tier."""
    pool = context.metadata.get("agent_pool") or context.metadata.get("agent_type")
    if not isinstance(pool, str):
        return None, None
    normalized = pool.strip().lower()
    if normalized == "background":
        return BACKGROUND_TIER, "agent_affinity:pool_background"
    if normalized == "interactive":
        return INTERACTIVE_TIER, "agent_affinity:pool_interactive"
    return None, None


def apply_agent_affinity(
    context: RoutingContext,
    redis_store: RedisStateStore,
    *,
    deprioritized_credentials: list[str],
    tier_preference: str | None = None,
    dry_run: bool = False,
) -> tuple[str | None, str | None, bool, bool, str | None, list[str]]:
    """Apply Redis sticky bindings and agent pool tier hints.

    Returns:
        preferred_credential_id, session_key, lock_model_family,
        cache_cold_start, credential_tier_preference, rules_applied
    """
    rules: list[str] = []
    session_key = build_session_key(context)
    lock_family = should_lock_model_family(context)
    if lock_family:
        rules.append("agent_affinity:lock_model_family")

    pool_tier, pool_rule = _agent_pool_tier(context)
    if pool_rule:
        rules.append(pool_rule)
    resolved_tier = pool_tier or tier_preference

    if not context.agent_id or not redis_store.enabled:
        if not context.agent_id:
            rules.append("agent_affinity:skip_no_agent_id")
        else:
            rules.append("agent_affinity:skip_redis_disabled")
        return None, session_key, lock_family, False, resolved_tier, rules

    affinity = redis_store.get_agent_affinity(context.agent_id)
    bound_cred = str(affinity["credential_id"]) if affinity and affinity.get("credential_id") else None
    cache_cold_start = False
    preferred: str | None = None

    needs_rebind = False
    if bound_cred:
        if _bound_credential_in_cooldown(bound_cred, context):
            needs_rebind = True
            cache_cold_start = True
            rules.append("agent_affinity:rebind_429")
            if not dry_run:
                redis_store.clear_agent_affinity(context.agent_id)
        elif bound_cred in deprioritized_credentials:
            needs_rebind = True
            rules.append("agent_affinity:rebind_deprioritized")

    if bound_cred and not needs_rebind:
        preferred = bound_cred
        rules.append("agent_affinity:sticky_hit")
        if not dry_run:
            redis_store.set_agent_affinity(
                context.agent_id,
                credential_id=bound_cred,
                model_family=affinity.get("model_family") if affinity else None,
            )
    else:
        new_cred = _pick_credential(context, deprioritized_credentials)
        if new_cred:
            preferred = new_cred
            rules.append("agent_affinity:bind")
            if not dry_run:
                redis_store.set_agent_affinity(
                    context.agent_id,
                    credential_id=new_cred,
                    model_family=_resolve_model_family(context),
                )
        elif needs_rebind:
            rules.append("agent_affinity:rebind_no_candidate")

    if session_key:
        rules.append("agent_affinity:session_key")

    return preferred, session_key, lock_family, cache_cold_start, resolved_tier, rules
