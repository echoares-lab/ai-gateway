"""Translator-owned model registry helpers.

The registry is Postgres-backed when DATABASE_URL is configured. Callers can
fall back to parsed LiteLLM config when the DB is unavailable so admin/status
and local unit tests remain fail-open.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from difflib import unified_diff
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
    diffs: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ModelRegistryReconcileRequest(BaseModel):
    dry_run: bool = True
    include_disabled: bool = False


class ModelRegistryReconcileResource(BaseModel):
    name: str
    kind: str
    changed: bool
    content: str
    diff: str = ""


class ModelRegistryReconcileResponse(BaseModel):
    accepted: bool = True
    dry_run: bool = True
    source: str
    registry_available: bool
    resources: list[ModelRegistryReconcileResource] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ModelRegistryMutationResponse(BaseModel):
    accepted: bool = True
    dry_run: bool = False
    registry_available: bool
    model: ModelRegistryRecord | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ModelProbeResponse(BaseModel):
    accepted: bool = True
    registry_available: bool
    model_id: str
    probe_status: str
    probe_http_status: int | None = None
    probe_checked_at: datetime
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
            family=self.family or (provider if provider != "unknown" else family_of(self.model_id)),
            upstream_model=self.upstream_model,
            litellm_model=self.litellm_model or f"openai/{self.upstream_model}",
            enabled=self.enabled,
            status=self.status,
            supports_tools=self.supports_tools,
            supports_vision=self.supports_vision,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=self.max_output_tokens,
            cost_tier=self.cost_tier if self.cost_tier is not None else cost_tier_of(self.model_id),
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


def normalize_model_id(model_id: str) -> str:
    model = model_id
    if model.startswith("AI-Gateway:"):
        model = model[len("AI-Gateway:") :]
    return model.replace(".", "-")


def _error(code: str, message: str, source: str) -> dict[str, Any]:
    return {"code": code, "message": message, "source": source}


def _entry_model_info(entry: dict[str, Any]) -> dict[str, Any]:
    info = entry.get("model_info")
    return info if isinstance(info, dict) else {}


def record_from_litellm_entry(entry: dict[str, Any]) -> ModelRegistryRecord | None:
    model_id = entry.get("model_name")
    params = entry.get("litellm_params") if isinstance(entry.get("litellm_params"), dict) else {}
    litellm_model = params.get("model")
    if not model_id or not litellm_model:
        return None
    upstream = str(litellm_model).split("/", 1)[1] if "/" in str(litellm_model) else str(litellm_model)
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
            "disable_background_health_check": info.get("disable_background_health_check"),
        },
        source="litellm-config",
        aliases=[],
    )


def record_from_cliproxy_model(entry: dict[str, Any]) -> ModelRegistryRecord | None:
    raw_model_id = entry.get("id") or entry.get("model")
    if not raw_model_id:
        return None
    model_id = normalize_model_id(str(raw_model_id))
    provider = provider_of(model_id)
    return ModelRegistryRecord(
        model_id=model_id,
        provider=provider,
        family=family_of(model_id),
        upstream_model=str(raw_model_id).removeprefix("AI-Gateway:"),
        litellm_model=f"openai/{str(raw_model_id).removeprefix('AI-Gateway:')}",
        enabled=True,
        status="UNKNOWN",
        cost_tier=cost_tier_of(model_id),
        policy_metadata={
            "cliproxy_model_id": str(raw_model_id),
            "owned_by": entry.get("owned_by"),
        },
        source="cliproxy",
    )


def merge_discovered_model(
    discovered: ModelRegistryRecord,
    current: ModelRegistryRecord | None,
) -> ModelRegistryRecord:
    if current is None:
        return discovered
    metadata = dict(current.policy_metadata)
    metadata.update(discovered.policy_metadata)
    return current.model_copy(
        update={
            "provider": discovered.provider,
            "family": discovered.family,
            "upstream_model": discovered.upstream_model,
            "litellm_model": discovered.litellm_model,
            "source": discovered.source,
            "policy_metadata": metadata,
        }
    )


def diff_discovered_models(
    discovered: list[ModelRegistryRecord],
    existing: list[ModelRegistryRecord],
) -> list[dict[str, Any]]:
    existing_by_id = {model.model_id: model for model in existing}
    diffs: list[dict[str, Any]] = []
    for model in discovered:
        current = existing_by_id.get(model.model_id)
        if current is None:
            diffs.append({"kind": "add", "model_id": model.model_id})
            continue
        changed_fields = []
        for field_name in ("provider", "family", "upstream_model", "litellm_model", "source"):
            if getattr(current, field_name) != getattr(model, field_name):
                changed_fields.append(field_name)
        if changed_fields:
            diffs.append(
                {
                    "kind": "update",
                    "model_id": model.model_id,
                    "fields": changed_fields,
                }
            )
    return diffs


def _litellm_model_info(model: ModelRegistryRecord) -> dict[str, Any]:
    info: dict[str, Any] = {}
    if model.supports_tools is not None:
        info["supports_function_calling"] = model.supports_tools
    if model.supports_vision is not None:
        info["supports_vision"] = model.supports_vision
    if model.max_input_tokens is not None:
        info["max_input_tokens"] = model.max_input_tokens
    if model.max_output_tokens is not None:
        info["max_output_tokens"] = model.max_output_tokens
    if model.policy_metadata.get("disable_background_health_check") is not None:
        info["disable_background_health_check"] = bool(model.policy_metadata["disable_background_health_check"])
    return info


def render_litellm_config_from_registry(models: list[ModelRegistryRecord]) -> str:
    active = sorted((model for model in models if model.enabled), key=lambda item: item.model_id)
    model_list = []
    for model in active:
        params = {
            "model": model.litellm_model,
            "api_base": model.policy_metadata.get("api_base", "http://cliproxy:8317/v1"),
            "api_key": "os.environ/CLIPROXY_API_KEY",
        }
        entry: dict[str, Any] = {
            "model_name": model.model_id,
            "litellm_params": params,
        }
        info = _litellm_model_info(model)
        if info:
            entry["model_info"] = info
        model_list.append(entry)

    fallbacks = []
    by_id = {model.model_id: model for model in active}
    for model in active:
        explicit = model.policy_metadata.get("fallbacks")
        if isinstance(explicit, list):
            fallback_ids = [str(item) for item in explicit if str(item) in by_id and str(item) != model.model_id]
        else:
            fallback_ids = [
                candidate.model_id
                for candidate in active
                if candidate.model_id != model.model_id and candidate.family == model.family
            ]
        if fallback_ids:
            fallbacks.append({model.model_id: sorted(fallback_ids)})

    rendered: dict[str, Any] = {"model_list": model_list}
    if fallbacks:
        rendered["litellm_settings"] = {"fallbacks": fallbacks}
    return yaml.safe_dump(rendered, sort_keys=False)


def render_gemini_map_from_registry(models: list[ModelRegistryRecord]) -> str:
    mapping: dict[str, str] = {}
    for model in sorted(models, key=lambda item: item.model_id):
        if not model.enabled:
            continue
        if model.upstream_model.startswith("gemini-") and model.upstream_model != model.model_id:
            mapping[model.upstream_model] = model.model_id
        for alias in model.aliases:
            if not isinstance(alias, dict):
                continue
            alias_name = str(alias.get("alias") or "")
            target = str(alias.get("target") or model.model_id)
            if alias_name.startswith("gemini-") and alias_name != target:
                mapping[alias_name] = target
    return json.dumps(dict(sorted(mapping.items())), indent=2) + "\n"


def _resource_diff(name: str, current: str | None, desired: str) -> tuple[bool, str]:
    current_text = current or ""
    if current_text == desired:
        return False, ""
    diff = unified_diff(
        current_text.splitlines(),
        desired.splitlines(),
        fromfile=f"current/{name}",
        tofile=f"desired/{name}",
        lineterm="",
    )
    return True, "\n".join(diff)


def build_reconcile_resources(
    models: list[ModelRegistryRecord],
    *,
    current_litellm_config: str | None = None,
    current_gemini_map: str | None = None,
    include_disabled: bool = False,
) -> list[ModelRegistryReconcileResource]:
    source_models = models if include_disabled else [model for model in models if model.enabled]
    litellm_content = render_litellm_config_from_registry(source_models)
    gemini_content = render_gemini_map_from_registry(source_models)
    litellm_changed, litellm_diff = _resource_diff("litellm-config.yaml", current_litellm_config, litellm_content)
    gemini_changed, gemini_diff = _resource_diff("gemini-model-map.json", current_gemini_map, gemini_content)
    return [
        ModelRegistryReconcileResource(
            name="litellm-config.yaml",
            kind="yaml",
            changed=litellm_changed,
            content=litellm_content,
            diff=litellm_diff,
        ),
        ModelRegistryReconcileResource(
            name="gemini-model-map.json",
            kind="json",
            changed=gemini_changed,
            content=gemini_content,
            diff=gemini_diff,
        ),
    ]


def load_models_from_litellm_config(path: str) -> RegistryLoadResult:
    try:
        with open(path, encoding="utf-8") as handle:
            doc = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        return RegistryLoadResult(
            source="litellm-config",
            registry_available=False,
            errors=[_error("config_not_found", f"{path} not found", "repo:litellm-config.yaml")],
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
    return RegistryLoadResult(source="litellm-config", registry_available=False, models=models)


def _database_url() -> str:
    return os.environ.get("MODEL_REGISTRY_DATABASE_URL") or os.environ.get("DATABASE_URL", "")


class ModelRegistryStore:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url if database_url is not None else _database_url()

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

    def update_probe_result(
        self,
        model_id: str,
        *,
        probe_status: str,
        probe_http_status: int | None,
        probe_checked_at: datetime,
    ) -> ModelRegistryRecord | None:
        if not self.enabled:
            raise RuntimeError("model registry database is not configured")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE model_registry
                SET probe_status = %s,
                    probe_http_status = %s,
                    probe_checked_at = %s
                WHERE model_id = %s
                """,
                (probe_status, probe_http_status, probe_checked_at, model_id),
            )
            if cur.rowcount == 0:
                conn.commit()
                return None
            conn.commit()
        return self.get_model(model_id)
