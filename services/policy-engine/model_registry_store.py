"""Read-only model_registry access for policy fallback traits."""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

MODEL_REGISTRY_TRAITS_SELECT = """
    SELECT
        r.model_id,
        r.provider,
        r.family,
        r.supports_tools,
        r.supports_vision,
        r.cost_tier,
        a.alias
    FROM model_registry r
    LEFT JOIN model_aliases a
        ON a.model_id = r.model_id
       AND a.alias = ANY(%s)
    WHERE r.model_id = ANY(%s)
       OR a.alias = ANY(%s)
"""


class DbConnection(Protocol):
    def cursor(self) -> Any: ...

    def close(self) -> None: ...


def _database_url() -> str:
    return os.environ.get("MODEL_REGISTRY_DATABASE_URL") or os.environ.get("DATABASE_URL", "")


def _trait_from_row(
    model_id: str,
    provider: str | None,
    family: str | None,
    supports_tools: bool | None,
    supports_vision: bool | None,
    cost_tier: int | None,
) -> dict[str, Any]:
    trait: dict[str, Any] = {
        "canonical_model_id": model_id,
        "provider": provider or "unknown",
    }
    if family:
        trait["family"] = family
    elif provider:
        trait["family"] = provider
    if supports_tools is not None:
        trait["tools"] = supports_tools
    if supports_vision is not None:
        trait["vision"] = supports_vision
    if cost_tier is not None:
        trait["cost"] = int(cost_tier)
    return trait


class ModelRegistryStore:
    """Fail-open read layer for model traits used by fallback evaluation."""

    def __init__(
        self,
        connect: Callable[[], DbConnection] | None,
        *,
        enabled: bool = True,
        fixtures: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._connect = connect
        self._enabled = enabled and connect is not None
        self._fixtures = fixtures or {}

    @classmethod
    def from_env(cls) -> ModelRegistryStore:
        url = _database_url().strip()
        if not url:
            return cls(None, enabled=False)
        try:
            import psycopg2  # type: ignore[import-untyped]

            def _connect() -> DbConnection:
                return psycopg2.connect(url)

            conn = _connect()
            conn.close()
            return cls(_connect)
        except Exception as exc:  # noqa: BLE001 - fail-open
            logger.warning("Postgres unavailable, model registry disabled: %s", exc)
            return cls(None, enabled=False)

    @property
    def enabled(self) -> bool:
        return self._enabled or bool(self._fixtures)

    def traits_for_models(self, models: list[str]) -> dict[str, dict[str, Any]]:
        requested = [model for model in models if model]
        if not requested:
            return {}

        traits: dict[str, dict[str, Any]] = {}
        for model in requested:
            fixture = self._fixtures.get(model)
            if fixture is not None:
                traits[model] = dict(fixture)

        if self._enabled:
            missing = [model for model in requested if model not in traits]
            if missing:
                try:
                    conn = self._connect()
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                MODEL_REGISTRY_TRAITS_SELECT,
                                (missing, missing, missing),
                            )
                            for row in cur.fetchall():
                                model_id, provider, family, tools, vision, cost, alias = row
                                trait = _trait_from_row(
                                    model_id,
                                    provider,
                                    family,
                                    tools,
                                    vision,
                                    cost,
                                )
                                traits[model_id] = trait
                                if alias:
                                    traits[alias] = trait
                    finally:
                        conn.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Model registry traits read failed: %s", exc)

        return traits
