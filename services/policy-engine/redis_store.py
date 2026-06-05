"""Redis hot state for policy-engine (Epic #38, issue 38-3)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from schemas import RateLimitSnapshot, RoutingContext

logger = logging.getLogger(__name__)

ROLLING_WINDOW_SECONDS = 300
DEFAULT_AFFINITY_TTL_SECONDS = int(os.environ.get("POLICY_AFFINITY_TTL_SECONDS", "3600"))


class RedisCommands(Protocol):
    def get(self, key: str) -> bytes | str | None: ...
    def set(self, key: str, value: str, ex: int | None = None) -> bool: ...
    def delete(self, key: str) -> int: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def rate_limit_key(provider: str, credential_id: str) -> str:
    return f"rate_limit:{provider}:{credential_id}"


def agent_affinity_key(agent_id: str) -> str:
    return f"affinity:agent:{agent_id}"


def profile_cache_key(scope: str, profile_id: str) -> str:
    return f"policy:cache:profile:{scope}:{profile_id}"


def decision_lkn_key(team_id: str, repo_name: str) -> str:
    return f"decision:lkn:{team_id}:{repo_name}"


PROFILE_CACHE_TTL_SECONDS = 300
DECISION_LKN_TTL_SECONDS = 600


class RedisStateStore:
    """Optional Redis backing for cooldown registry and agent affinity."""

    def __init__(self, client: RedisCommands | None, *, enabled: bool = True) -> None:
        self._client = client
        self._enabled = enabled and client is not None

    @classmethod
    def from_env(cls) -> RedisStateStore:
        url = os.environ.get("REDIS_URL", "").strip()
        if not url:
            return cls(None, enabled=False)
        try:
            import redis  # type: ignore[import-untyped]

            client = redis.Redis.from_url(url, decode_responses=True)
            client.ping()
            return cls(client)
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("Redis unavailable, policy hot state disabled: %s", exc)
            return cls(None, enabled=False)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _get_json(self, key: str) -> dict[str, Any] | None:
        if not self._enabled:
            return None
        try:
            raw = self._client.get(key)
            if not raw:
                return None
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis read failed for %s: %s", key, exc)
            return None

    def _set_json(self, key: str, payload: dict[str, Any], ttl_seconds: int | None) -> bool:
        if not self._enabled:
            return False
        try:
            ex = max(int(ttl_seconds), 1) if ttl_seconds is not None else None
            self._client.set(key, json.dumps(payload), ex=ex)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis write failed for %s: %s", key, exc)
            return False

    def get_rate_limit_state(self, provider: str, credential_id: str) -> dict[str, Any] | None:
        return self._get_json(rate_limit_key(provider, credential_id))

    def get_agent_affinity(self, agent_id: str) -> dict[str, Any] | None:
        return self._get_json(agent_affinity_key(agent_id))

    def get_profile_cache(self, scope: str, profile_id: str) -> dict[str, Any] | None:
        return self._get_json(profile_cache_key(scope, profile_id))

    def set_profile_cache(
        self,
        scope: str,
        profile_id: str,
        profile: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
    ) -> bool:
        ttl = ttl_seconds if ttl_seconds is not None else PROFILE_CACHE_TTL_SECONDS
        return self._set_json(profile_cache_key(scope, profile_id), profile, ttl)

    def get_decision_lkn(self, team_id: str, repo_name: str) -> dict[str, Any] | None:
        return self._get_json(decision_lkn_key(team_id, repo_name))

    def set_decision_lkn(
        self,
        team_id: str,
        repo_name: str,
        decision: dict[str, Any],
        *,
        ttl_seconds: int | None = None,
    ) -> bool:
        ttl = ttl_seconds if ttl_seconds is not None else DECISION_LKN_TTL_SECONDS
        return self._set_json(decision_lkn_key(team_id, repo_name), decision, ttl)

    def set_agent_affinity(
        self,
        agent_id: str,
        *,
        credential_id: str,
        model_family: str | None = None,
        ttl_seconds: int | None = None,
    ) -> bool:
        payload = {
            "credential_id": credential_id,
            "model_family": model_family,
            "bound_at": _utcnow().isoformat(),
        }
        ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_AFFINITY_TTL_SECONDS
        return self._set_json(agent_affinity_key(agent_id), payload, ttl)

    def clear_agent_affinity(self, agent_id: str) -> bool:
        if not self._enabled:
            return False
        try:
            self._client.delete(agent_affinity_key(agent_id))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis delete failed for agent %s: %s", agent_id, exc)
            return False

    def _is_stale_event(self, existing: dict[str, Any], event_at: datetime) -> bool:
        last_event = _parse_dt(existing.get("last_event_at"))
        return bool(last_event and event_at <= last_event)

    def apply_credential_cooldown(
        self,
        provider: str,
        credential_id: str,
        *,
        cooldown_until: datetime | None = None,
        cooldown_seconds: int = 60,
        event_at: datetime | None = None,
        status: str = "DEGRADED",
    ) -> dict[str, Any] | None:
        """Set cooldown registry entry from credential-prober transition (idempotent)."""
        if not self._enabled:
            return None
        now = _utcnow()
        event_time = event_at or now
        if cooldown_until is None:
            cooldown_until = now + timedelta(seconds=cooldown_seconds)
        existing = self.get_rate_limit_state(provider, credential_id) or {}
        if self._is_stale_event(existing, event_time):
            return existing
        payload = {
            "cooldown_until": cooldown_until.isoformat(),
            "last_429_at": existing.get("last_429_at"),
            "rolling_429_count": int(existing.get("rolling_429_count") or 0),
            "last_event_at": event_time.isoformat(),
            "source": "credential_event",
            "status": status,
        }
        ttl = int(max((cooldown_until - now).total_seconds(), 1))
        self._set_json(rate_limit_key(provider, credential_id), payload, ttl)
        return payload

    def record_rate_limit_429(
        self,
        provider: str,
        credential_id: str,
        *,
        cooldown_until: datetime | None = None,
        cooldown_seconds: int = 60,
        event_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Increment rolling 429 count and set cooldown TTL on the rate_limit key."""
        if not self._enabled:
            return None
        now = _utcnow()
        event_time = event_at or now
        if cooldown_until is None:
            cooldown_until = now + timedelta(seconds=cooldown_seconds)
        key = rate_limit_key(provider, credential_id)
        existing = self.get_rate_limit_state(provider, credential_id) or {}
        if self._is_stale_event(existing, event_time):
            return existing
        last_at = _parse_dt(existing.get("last_429_at"))
        rolling = int(existing.get("rolling_429_count") or 0)
        if last_at and (now - last_at).total_seconds() > ROLLING_WINDOW_SECONDS:
            rolling = 0
        rolling += 1
        payload = {
            "cooldown_until": cooldown_until.isoformat(),
            "last_429_at": now.isoformat(),
            "rolling_429_count": rolling,
            "last_event_at": event_time.isoformat(),
            "source": "rate_limited_event",
        }
        ttl = int(max((cooldown_until - now).total_seconds(), 1))
        self._set_json(key, payload, ttl)
        return payload

    def rate_limit_to_snapshot(self, provider: str, credential_id: str) -> RateLimitSnapshot | None:
        data = self.get_rate_limit_state(provider, credential_id)
        if not data:
            return None
        cooldown_until = _parse_dt(data.get("cooldown_until"))
        now = _utcnow()
        in_cooldown = bool(cooldown_until and cooldown_until > now)
        return RateLimitSnapshot(
            provider=provider,
            credential_id=credential_id,
            in_cooldown=in_cooldown,
            cooldown_until=cooldown_until,
            rolling_429_count_5m=int(data.get("rolling_429_count") or 0),
        )

    def merge_rate_limits_from_redis(self, context: RoutingContext) -> RoutingContext:
        """Merge Redis cooldown registry entries into context.rate_limits (fail-open)."""
        if not self._enabled:
            return context

        by_cred: dict[tuple[str | None, str | None], RateLimitSnapshot] = {}
        for snap in context.rate_limits:
            by_cred[(snap.provider, snap.credential_id)] = snap

        keys_to_fetch: list[tuple[str, str]] = []
        for snap in context.rate_limits:
            if snap.provider and snap.credential_id:
                keys_to_fetch.append((snap.provider, snap.credential_id))

        if context.agent_id:
            aff = self.get_agent_affinity(context.agent_id)
            if aff and aff.get("credential_id"):
                cred = str(aff["credential_id"])
                prov = context.metadata.get("affinity_provider")
                if isinstance(prov, str) and prov:
                    keys_to_fetch.append((prov, cred))

        seen: set[tuple[str, str]] = set()
        for provider, credential_id in keys_to_fetch:
            if (provider, credential_id) in seen:
                continue
            seen.add((provider, credential_id))
            redis_snap = self.rate_limit_to_snapshot(provider, credential_id)
            if not redis_snap:
                continue
            existing = by_cred.get((provider, credential_id))
            if existing:
                merged = existing.model_copy(
                    update={
                        "in_cooldown": redis_snap.in_cooldown or existing.in_cooldown,
                        "cooldown_until": redis_snap.cooldown_until or existing.cooldown_until,
                        "rolling_429_count_5m": max(
                            existing.rolling_429_count_5m,
                            redis_snap.rolling_429_count_5m,
                        ),
                    }
                )
                by_cred[(provider, credential_id)] = merged
            else:
                by_cred[(provider, credential_id)] = redis_snap

        if not by_cred:
            return context
        return context.model_copy(update={"rate_limits": list(by_cred.values())})
