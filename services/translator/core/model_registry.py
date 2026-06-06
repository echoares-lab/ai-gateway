"""Translator-owned model registry helpers.

The registry is Postgres-backed when DATABASE_URL is configured. Callers can
fall back to parsed LiteLLM config when the DB is unavailable so admin/status
and local unit tests remain fail-open.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import yaml
from pydantic import BaseModel, Field

try:  # pragma: no cover - exercised only when psycopg2 is installed/configured
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
except Exception:  # pragma: no cover - local unit env may not have psycopg2
    psycopg2 = None
    Json = None
    RealDictCursor = None


class ModelRegistryRecord(BaseModel):
    model_id: str
    provider: str = "unknown"
    family: str = "unknown"
    upstream_model: str
    litellm_model: str
    enabled: bool = True
    status: str = "UNKNOWN"
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    cost_tier: int | None = Field(default=None, ge=1, le=3)
    policy_metadata: dict[str, Any] = Field(default_factory=dict)
    probe_status: str | None = None
    probe_http_status: int | None = None
    probe_checked_at: datetime | None = None
    source: str = "manual"
    aliases: list[dict[str, Any]] = Field(default_factory=list)


class ModelRegistryListResponse(BaseModel):
    source: str
    registry_available: bool
    models: list[ModelRegistryRecord] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ModelRegistrySyncRequest(BaseModel):
    dry_run: bool = True
    source: str = "litellm-config"


class ModelRegistrySyncResponse(BaseModel):
    dry_run: bool
    source: str
    registry_available: bool
    imported_count: int = 0
    skipped_count: int = 0
    models: list[ModelRegistryRecord] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ModelRegistryMutationResponse(BaseModel):
    accepted: bool = True
    dry_run: bool = False
    registry_available: bool
    model: ModelRegistryRecord | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ModelRegistryWriteRequest(BaseModel):
    model_id: str
    provider: str | None = None
    family: str | None = None
    upstream_model: str
    litellm_model: str | None = None
    enabled: bool = True
    status: str = "UNKNOWN"
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    cost_tier: int | None = Field(default=None, ge=1, le=3)
    policy_metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"

    def to_record(self) -> ModelRegistryRecord:
        provider = self.provider or provider_of(self.model_id)
        return ModelRegistryRecord(
            model_id=self.model_id,
            provider=provider,
            family=self.family
            or (provider if provider != "unknown" else family_of(self.model_id)),
            upstream_model=self.upstream_model,
            litellm_model=self.litellm_model or f"openai/{self.upstream_model}",
            enabled=self.enabled,
            status=self.status,
            supports_tools=self.supports_tools,
            supports_vision=self.supports_vision,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=self.max_output_tokens,
            cost_tier=self.cost_tier
            if self.cost_tier is not None
            else cost_tier_of(self.model_id),
            policy_metadata=self.policy_metadata,
            source=self.source,
        )


class ModelRegistryPatchRequest(BaseModel):
    provider: str | None = None
    family: str | None = None
    upstream_model: str | None = None
    litellm_model: str | None = None
    enabled: bool | None = None
    status: str | None = None
    supports_tools: bool | None = None
    supports_vision: bool | None = None
    max_input_tokens: int | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=0)
    cost_tier: int | None = Field(default=None, ge=1, le=3)
    policy_metadata: dict[str, Any] | None = None
    source: str | None = None

    def apply(self, current: ModelRegistryRecord) -> ModelRegistryRecord:
        updates = {k: v for k, v in self.model_dump().items() if v is not None}
        return current.model_copy(update=updates)


@dataclass
class RegistryLoadResult:
    source: str
    registry_available: bool
    models: list[ModelRegistryRecord] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def provider_of(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "codex")):
        return "openai"
    if m.startswith("gemini"):
        return "gemini"
    if m.startswith("grok"):
        return "xai"
    if m.startswith(("kimi", "moonshot")):
        return "moonshot"
    return "unknown"


def family_of(model: str) -> str:
    provider = provider_of(model)
    return provider if provider != "unknown" else "unknown"


def cost_tier_of(model: str) -> int | None:
    m = (model or "").lower()
    if any(part in m for part in ("haiku", "mini", "lite", "flash")):
        return 1
    if any(part in m for part in ("opus", "pro-high", "gpt-5-5")):
        return 3
    return 2 if provider_of(m) != "unknown" else None


def _error(code: str, message: str, source: str) -> dict[str, Any]:
    return {"code": code, "message": message, "source": source}


def _entry_model_info(entry: dict[str, Any]) -> dict[str, Any]:
    info = entry.get("model_info")
    return info if isinstance(info, dict) else {}


def record_from_litellm_entry(entry: dict[str, Any]) -> ModelRegistryRecord | None:
    model_id = entry.get("model_name")
    params = (
        entry.get("litellm_params")
        if isinstance(entry.get("litellm_params"), dict)
        else {}
    )
    litellm_model = params.get("model")
    if not model_id or not litellm_model:
        return None
    upstream = (
        str(litellm_model).split("/", 1)[1]
        if "/" in str(litellm_model)
        else str(litellm_model)
    )
    info = _entry_model_info(entry)
    provider = provider_of(str(model_id))
    return ModelRegistryRecord(
        model_id=str(model_id),
        provider=provider,
        family=family_of(str(model_id)),
        upstream_model=upstream,
        litellm_model=str(litellm_model),
        enabled=True,
        status="UNKNOWN",
        supports_tools=info.get("supports_function_calling"),
        supports_vision=info.get("supports_vision"),
        max_input_tokens=info.get("max_input_tokens"),
        max_output_tokens=info.get("max_output_tokens"),
        cost_tier=cost_tier_of(str(model_id)),
        policy_metadata={
            "api_base": params.get("api_base"),
            "disable_background_health_check": info.get(
                "disable_background_health_check"
            ),
        },
        source="litellm-config",
        aliases=[],
    )


def load_models_from_litellm_config(path: str) -> RegistryLoadResult:
    try:
        with open(path, encoding="utf-8") as handle:
            doc = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        return RegistryLoadResult(
            source="litellm-config",
            registry_available=False,
            errors=[
                _error(
                    "config_not_found", f"{path} not found", "repo:litellm-config.yaml"
                )
            ],
        )
    except Exception as exc:
        return RegistryLoadResult(
            source="litellm-config",
            registry_available=False,
            errors=[
                _error(
                    "config_parse_error",
                    f"{type(exc).__name__}: {exc}",
                    "repo:litellm-config.yaml",
                )
            ],
        )

    models: list[ModelRegistryRecord] = []
    for entry in doc.get("model_list", []) or []:
        if not isinstance(entry, dict):
            continue
        record = record_from_litellm_entry(entry)
        if record is not None:
            models.append(record)
    return RegistryLoadResult(
        source="litellm-config", registry_available=False, models=models
    )


def _database_url() -> str:
    return os.environ.get("MODEL_REGISTRY_DATABASE_URL") or os.environ.get(
        "DATABASE_URL", ""
    )


class ModelRegistryStore:
    def __init__(self, database_url: str | None = None):
        self.database_url = (
            database_url if database_url is not None else _database_url()
        )

    @property
    def enabled(self) -> bool:
        return bool(self.database_url and psycopg2 is not None)

    def _connect(self):
        if not self.enabled:
            raise RuntimeError("model registry database is not configured")
        return psycopg2.connect(self.database_url)

    def list_models(self) -> RegistryLoadResult:
        if not self.enabled:
            return RegistryLoadResult(
                source="postgres:model_registry",
                registry_available=False,
                errors=[
                    _error(
                        "registry_unavailable",
                        "DATABASE_URL or psycopg2 unavailable",
                        "postgres:model_registry",
                    )
                ],
            )
        try:
            with (
                self._connect() as conn,
                conn.cursor(cursor_factory=RealDictCursor) as cur,
            ):
                cur.execute(
                    """
                    SELECT r.*, COALESCE(
                        jsonb_agg(
                            jsonb_build_object(
                                'alias', a.alias,
                                'provider', a.provider,
                                'alias_kind', a.alias_kind,
                                'target', a.target,
                                'metadata', a.metadata
                            )
                        ) FILTER (WHERE a.alias IS NOT NULL),
                        '[]'::jsonb
                    ) AS aliases
                    FROM model_registry r
                    LEFT JOIN model_aliases a ON a.model_id = r.model_id
                    GROUP BY r.model_id
                    ORDER BY r.provider, r.model_id
                    """
                )
                rows = cur.fetchall()
        except Exception as exc:
            return RegistryLoadResult(
                source="postgres:model_registry",
                registry_available=False,
                errors=[
                    _error(
                        "registry_read_error",
                        f"{type(exc).__name__}: {exc}",
                        "postgres:model_registry",
                    )
                ],
            )
        return RegistryLoadResult(
            source="postgres:model_registry",
            registry_available=True,
            models=[ModelRegistryRecord.model_validate(dict(row)) for row in rows],
        )

    def get_model(self, model_id: str) -> ModelRegistryRecord | None:
        result = self.list_models()
        for model in result.models:
            if model.model_id == model_id:
                return model
        return None

    def upsert_models(self, models: list[ModelRegistryRecord]) -> int:
        if not self.enabled:
            raise RuntimeError("model registry database is not configured")
        if not models:
            return 0
        with self._connect() as conn, conn.cursor() as cur:
            for model in models:
                cur.execute(
                    """
                    INSERT INTO model_registry (
                        model_id, provider, family, upstream_model, litellm_model,
                        enabled, status, supports_tools, supports_vision,
                        max_input_tokens, max_output_tokens, cost_tier,
                        policy_metadata, source
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (model_id) DO UPDATE SET
                        provider = EXCLUDED.provider,
                        family = EXCLUDED.family,
                        upstream_model = EXCLUDED.upstream_model,
                        litellm_model = EXCLUDED.litellm_model,
                        enabled = EXCLUDED.enabled,
                        supports_tools = EXCLUDED.supports_tools,
                        supports_vision = EXCLUDED.supports_vision,
                        max_input_tokens = EXCLUDED.max_input_tokens,
                        max_output_tokens = EXCLUDED.max_output_tokens,
                        cost_tier = EXCLUDED.cost_tier,
                        policy_metadata = EXCLUDED.policy_metadata,
                        source = EXCLUDED.source
                    """,
                    (
                        model.model_id,
                        model.provider,
                        model.family,
                        model.upstream_model,
                        model.litellm_model,
                        model.enabled,
                        model.status,
                        model.supports_tools,
                        model.supports_vision,
                        model.max_input_tokens,
                        model.max_output_tokens,
                        model.cost_tier,
                        Json(model.policy_metadata),
                        model.source,
                    ),
                )
            conn.commit()
        return len(models)

    def upsert_model(self, model: ModelRegistryRecord) -> ModelRegistryRecord:
        self.upsert_models([model])
        return self.get_model(model.model_id) or model

    def disable_model(self, model_id: str) -> ModelRegistryRecord | None:
        current = self.get_model(model_id)
        if current is None:
            return None
        disabled = current.model_copy(update={"enabled": False, "status": "DISABLED"})
        return self.upsert_model(disabled)

    def hard_delete_model(self, model_id: str) -> bool:
        if not self.enabled:
            raise RuntimeError("model registry database is not configured")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM model_registry WHERE model_id = %s", (model_id,))
            deleted = cur.rowcount > 0
            conn.commit()
        return deleted
