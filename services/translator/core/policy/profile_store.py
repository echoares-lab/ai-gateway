"""Postgres read layer for policy_profiles (Epic #38, issue 38-5)."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Callable, Protocol

from core.policy.schemas import PolicyProfile, PolicyScope, TenancyContext

if TYPE_CHECKING:
    from core.policy.redis_store import RedisStateStore

logger = logging.getLogger(__name__)

PROFILE_SELECT = """
    SELECT profile_id, scope, scope_id, allowed_models, denied_models,
           fallback_chain_override, credential_tier_preference, policy_json, enabled
    FROM policy_profiles
    WHERE scope = %s AND scope_id = %s AND enabled = true
"""

SCOPE_RESOLUTION_ORDER: tuple[PolicyScope, ...] = (
    PolicyScope.ORG,
    PolicyScope.WORKSPACE,
    PolicyScope.TEAM,
    PolicyScope.REPO,
)

TENANCY_SCOPE_FIELDS: dict[PolicyScope, str] = {
    PolicyScope.ORG: "tenant_id",
    PolicyScope.WORKSPACE: "workspace_id",
    PolicyScope.TEAM: "team_id",
    PolicyScope.REPO: "repo_name",
}


class DbConnection(Protocol):
    def cursor(self) -> Any: ...

    def close(self) -> None: ...


def _row_to_profile(row: tuple[Any, ...]) -> PolicyProfile:
    return PolicyProfile(
        profile_id=row[0],
        scope=PolicyScope(row[1]),
        scope_id=row[2],
        allowed_models=list(row[3] or []),
        denied_models=list(row[4] or []),
        fallback_chain_override=list(row[5] or []),
        credential_tier_preference=row[6],
        policy_json=dict(row[7] or {}),
        enabled=bool(row[8]),
    )


def scope_ids_for_tenancy(tenancy: TenancyContext) -> list[tuple[PolicyScope, str]]:
    """Return (scope, scope_id) pairs from least to most specific."""
    pairs: list[tuple[PolicyScope, str]] = []
    for scope in SCOPE_RESOLUTION_ORDER:
        field = TENANCY_SCOPE_FIELDS[scope]
        value = getattr(tenancy, field, None)
        if value:
            pairs.append((scope, value))
    return pairs


class ProfileStore:
    """Read-only policy_profiles access. Fail-open when Postgres is unavailable."""

    def __init__(
        self,
        connect: Callable[[], DbConnection] | None,
        *,
        enabled: bool = True,
        profiles: dict[tuple[str, str], PolicyProfile] | None = None,
    ) -> None:
        self._connect = connect
        self._enabled = enabled and connect is not None
        self._fixtures = profiles or {}

    @classmethod
    def from_env(cls) -> ProfileStore:
        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            return cls(None, enabled=False)
        try:
            import psycopg2  # type: ignore[import-untyped]

            def _connect() -> DbConnection:
                return psycopg2.connect(url)

            conn = _connect()
            conn.close()
            return cls(_connect)
        except Exception as exc:  # noqa: BLE001 — fail-open
            logger.warning("Postgres unavailable, policy profiles disabled: %s", exc)
            return cls(None, enabled=False)

    @property
    def enabled(self) -> bool:
        return self._enabled or bool(self._fixtures)

    def get_profile(
        self,
        scope: PolicyScope | str,
        scope_id: str,
        *,
        redis_store: RedisStateStore | None = None,
        cache_write: bool = True,
    ) -> PolicyProfile | None:
        scope_value = scope.value if isinstance(scope, PolicyScope) else scope
        fixture = self._fixtures.get((scope_value, scope_id))
        if fixture is not None:
            return fixture

        if redis_store is not None and redis_store.enabled:
            cached = redis_store.get_profile_cache(scope_value, scope_id)
            if cached:
                try:
                    return PolicyProfile.model_validate(cached)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Invalid profile cache for %s:%s: %s",
                        scope_value,
                        scope_id,
                        exc,
                    )

        if not self._enabled:
            return None
        try:
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(PROFILE_SELECT, (scope_value, scope_id))
                    row = cur.fetchone()
            finally:
                conn.close()
            if not row:
                return None
            profile = _row_to_profile(row)
            if (
                redis_store is not None
                and redis_store.enabled
                and cache_write
            ):
                redis_store.set_profile_cache(
                    scope_value,
                    scope_id,
                    profile.model_dump(mode="json"),
                )
            return profile
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Postgres read failed for profile %s:%s: %s",
                scope_value,
                scope_id,
                exc,
            )
            return None

    def get_profiles_for_tenancy(
        self,
        tenancy: TenancyContext,
        *,
        redis_store: RedisStateStore | None = None,
        cache_write: bool = True,
    ) -> list[PolicyProfile]:
        """Load enabled profiles from org → workspace → team → repo."""
        profiles: list[PolicyProfile] = []
        for scope, scope_id in scope_ids_for_tenancy(tenancy):
            profile = self.get_profile(
                scope,
                scope_id,
                redis_store=redis_store,
                cache_write=cache_write,
            )
            if profile is not None:
                profiles.append(profile)
        return profiles
