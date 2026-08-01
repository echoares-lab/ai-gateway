"""Pure, bounded construction of the unified configuration snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import yaml

SCHEMA = "config-snapshot.v1"
MAX_ENTRIES = 256
MAX_STRING = 512
MAX_DEPTH = 8
MAX_DEPLOYED_CONFIG_BYTES = 1024 * 1024
SAFE_ROUTER_SETTINGS = ("allowed_fails", "cooldown_time", "num_retries", "routing_strategy")
ENV_REFERENCE = re.compile(r"(?:os\.environ/|\$\{)([A-Z_][A-Z0-9_]*)\}?")

_SOURCE_DETAILS = (
    ("litellm-config", "deployed-file"),
    ("model-registry", "registry"),
    ("runtime-visible-models", "live-api"),
)
_SOURCE_ERROR_CODES = {"source_missing", "source_invalid", "source_timeout", "source_unavailable"}
_SOURCE_STATUSES = {"ok", "missing", "invalid", "unavailable"}
_SAFE_PROVIDER_FAMILIES = {
    "anthropic",
    "azure",
    "bedrock",
    "cohere",
    "gemini",
    "google",
    "groq",
    "mistral",
    "moonshot",
    "openai",
    "vertex_ai",
    "xai",
}
_SAFE_MCP_TRANSPORTS = {"http", "sse", "stdio", "streamable-http", "streamable_http", "websocket"}
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|token|url|uri|host|path|command|args)", re.I
)
_SENSITIVE_VALUE = re.compile(r"(?:https?://|(?:sk|pk)-|secret|/home/|/root/)", re.I)


@dataclass(frozen=True)
class SnapshotInputs:
    litellm_yaml: str | None
    litellm_status: str
    registry_model_ids: tuple[str, ...] | None
    registry_status: str
    runtime_model_ids: tuple[str, ...] | None
    runtime_status: str
    environment: Mapping[str, str]
    generated_at: datetime
    source_errors: tuple[tuple[str, str], ...] = ()


def _bounded_text(value: object) -> str:
    """Return a string without exposing secret-looking values or overlong text."""
    text = str(value)
    if _SENSITIVE_VALUE.search(text) or text.startswith("/"):
        return "[redacted]"
    return text[:MAX_STRING]


def _safe_provider_family(model_name: str, params: Mapping[str, Any]) -> str:
    """Project only a known provider family, never an upstream endpoint or config key."""
    candidate = params.get("model") if isinstance(params, Mapping) else None
    for value in (candidate, model_name):
        if not isinstance(value, str):
            continue
        family = value.split("/", 1)[0].lower().replace("-", "_")
        if family in _SAFE_PROVIDER_FAMILIES:
            return family
    return "other"


def _extract_environment_references(document: Mapping[str, Any]) -> list[str]:
    """Find referenced environment variable names without retaining their values."""
    references: set[str] = set()

    def visit(value: object, depth: int) -> None:
        if depth >= MAX_DEPTH:
            return
        if isinstance(value, Mapping):
            for nested in value.values():
                visit(nested, depth + 1)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested, depth + 1)
        elif isinstance(value, str):
            references.update(ENV_REFERENCE.findall(value))

    visit(document, 0)
    return sorted(references)[:MAX_ENTRIES]


def _sanitize_for_digest(value: object, depth: int = 0, key: str = "") -> object:
    if depth >= MAX_DEPTH or _SENSITIVE_KEY.search(key):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {
            _bounded_text(name): _sanitize_for_digest(item, depth + 1, str(name))
            for name, item in sorted(value.items(), key=lambda item: str(item[0]))[:MAX_ENTRIES]
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_digest(item, depth + 1) for item in list(value)[:MAX_ENTRIES]]
    if isinstance(value, str):
        return _bounded_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _bounded_text(value)


def _sanitized_projection_digest(projection: Mapping[str, Any]) -> str:
    """Hash only canonical, redacted structural data."""
    canonical = json.dumps(_sanitize_for_digest(projection), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_status(value: object) -> str:
    return value if isinstance(value, str) and value in _SOURCE_STATUSES else "unavailable"


def _safe_alias(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return _bounded_text(value)


def _normalised_aliases(values: tuple[str, ...] | None, *, strip_public_prefix: bool = False) -> list[str]:
    aliases: set[str] = set()
    for value in values or ():
        if not isinstance(value, str):
            continue
        if strip_public_prefix and value.startswith("AI-Gateway:"):
            value = value[len("AI-Gateway:") :]
        alias = _safe_alias(value)
        if alias:
            aliases.add(alias)
    return sorted(aliases)[:MAX_ENTRIES]


def _safe_router_value(value: object) -> bool | int | float | str | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value)
    return None


def _project_mcp(document: Mapping[str, Any]) -> list[dict[str, str]]:
    servers = document.get("mcp_servers")
    if not isinstance(servers, Mapping):
        return []
    projected: dict[str, str] = {}
    for alias, server in servers.items():
        safe_alias = _safe_alias(alias)
        if not safe_alias or not isinstance(server, Mapping):
            continue
        transport = server.get("transport")
        if isinstance(transport, str) and transport.lower() in _SAFE_MCP_TRANSPORTS:
            projected[safe_alias] = transport.lower()
    return [{"alias": alias, "transport": transport} for alias, transport in sorted(projected.items())[:MAX_ENTRIES]]


def _project_fallbacks(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_fallbacks = document.get("fallbacks")
    pairs: dict[str, list[str]] = {}
    if not isinstance(raw_fallbacks, list):
        return []
    for entry in raw_fallbacks:
        if not isinstance(entry, Mapping):
            continue
        for source, targets in entry.items():
            safe_source = _safe_alias(source)
            if not safe_source or not isinstance(targets, (list, tuple)):
                continue
            safe_targets = sorted({alias for target in targets if (alias := _safe_alias(target))})[:MAX_ENTRIES]
            if safe_targets:
                pairs[safe_source] = safe_targets
    return [{"from": source, "to": targets} for source, targets in sorted(pairs.items())[:MAX_ENTRIES]]


def _parse_document(raw_yaml: str | None) -> tuple[Mapping[str, Any], bool]:
    if raw_yaml is None or not isinstance(raw_yaml, str) or len(raw_yaml.encode("utf-8")) > MAX_DEPLOYED_CONFIG_BYTES:
        return {}, False
    try:
        document = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        return {}, False
    return (document, True) if isinstance(document, Mapping) else ({}, False)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _error_code_for_status(status: str) -> str:
    return {"missing": "source_missing", "invalid": "source_invalid"}.get(status, "source_unavailable")


def build_config_snapshot(inputs: SnapshotInputs) -> dict[str, Any]:
    """Build a deterministic snapshot from already-acquired, trusted source inputs."""
    document, document_valid = _parse_document(inputs.litellm_yaml)
    litellm_status = _source_status(inputs.litellm_status)
    if inputs.litellm_yaml is None:
        if litellm_status == "ok":
            litellm_status = "missing"
    elif not document_valid:
        litellm_status = "invalid"
    registry_status = _source_status(inputs.registry_status)
    runtime_status = _source_status(inputs.runtime_status)

    model_list = document.get("model_list", []) if document_valid else []
    if not isinstance(model_list, list):
        model_list = []
        document_valid = False
        litellm_status = "invalid"

    configured: set[str] = set()
    provider_by_alias: dict[str, str] = {}
    for entry in model_list:
        if not isinstance(entry, Mapping):
            continue
        alias = _safe_alias(entry.get("model_name"))
        if not alias:
            continue
        configured.add(alias)
        params = entry.get("litellm_params")
        family = _safe_provider_family(alias, params if isinstance(params, Mapping) else {})
        provider_by_alias[alias] = min(provider_by_alias.get(alias, family), family)

    configured_aliases = sorted(configured)[:MAX_ENTRIES]
    registry_aliases = _normalised_aliases(inputs.registry_model_ids)
    runtime_aliases = _normalised_aliases(inputs.runtime_model_ids, strip_public_prefix=True)
    providers = [
        {"alias": alias, "family": provider_by_alias[alias]}
        for alias in configured_aliases
        if alias in provider_by_alias
    ]
    routing = {
        setting: safe_value
        for setting in SAFE_ROUTER_SETTINGS
        if isinstance(document.get("router_settings"), Mapping)
        and (safe_value := _safe_router_value(document["router_settings"].get(setting))) is not None
    }
    mcp = _project_mcp(document)
    environment_references = _extract_environment_references(document)
    environment = [{"name": name, "present": name in inputs.environment} for name in environment_references]
    validation = [
        {"id": "deployed-config", "status": "pass" if document_valid else "fail"},
        {
            "id": "environment-references",
            "status": "pass" if all(item["present"] for item in environment) else "warn",
        },
    ]

    statuses = {
        "litellm-config": litellm_status,
        "model-registry": registry_status,
        "runtime-visible-models": runtime_status,
    }
    source_errors: dict[str, str] = {}
    for source, code in inputs.source_errors[:MAX_ENTRIES]:
        if source in statuses and code in _SOURCE_ERROR_CODES:
            source_errors[source] = code
    for source, status in statuses.items():
        if status != "ok" and source not in source_errors:
            source_errors[source] = _error_code_for_status(status)

    configured_set = set(configured_aliases)
    registry_set = set(registry_aliases)
    runtime_set = set(runtime_aliases)
    drift_fields = {
        "configured_only": sorted(configured_set - registry_set)[:MAX_ENTRIES],
        "registry_only": sorted(registry_set - configured_set)[:MAX_ENTRIES],
        "runtime_only": sorted(runtime_set - configured_set)[:MAX_ENTRIES],
        "missing_at_runtime": sorted((configured_set | registry_set) - runtime_set)[:MAX_ENTRIES],
        "registry_override": configured_set != registry_set,
    }
    if any(status != "ok" for status in statuses.values()):
        drift = {
            "status": "unknown",
            **{key: [] for key in drift_fields if key != "registry_override"},
            "registry_override": False,
        }
    elif any(drift_fields[key] for key in ("configured_only", "registry_only", "runtime_only", "missing_at_runtime")):
        drift = {"status": "drifted", **drift_fields}
    else:
        drift = {"status": "clean", **drift_fields}

    source_projections = {
        "litellm-config": {
            "models": {
                "configured": configured_aliases,
                "providers": providers,
                "fallbacks": _project_fallbacks(document),
            },
            "routing": routing,
            "mcp": mcp,
            "environment": [item["name"] for item in environment],
        },
        "model-registry": {"model_ids": registry_aliases},
        "runtime-visible-models": {"model_ids": runtime_aliases},
    }
    observed_at = _iso_utc(inputs.generated_at)
    sources = [
        {
            "id": identifier,
            "kind": kind,
            "status": statuses[identifier],
            "digest": _sanitized_projection_digest(source_projections[identifier]),
            "observed_at": observed_at,
        }
        for identifier, kind in _SOURCE_DETAILS
    ]
    errors = [{"source": source, "code": code} for source, code in sorted(source_errors.items())[:MAX_ENTRIES]]
    status = "ok"
    if (
        any(value != "ok" for value in statuses.values())
        or any(item["status"] != "pass" for item in validation)
        or drift["status"] != "clean"
    ):
        status = "degraded"
    return {
        "schema": SCHEMA,
        "status": status,
        "generated_at": observed_at,
        "sources": sources,
        "models": {
            "configured": configured_aliases,
            "registry": registry_aliases,
            "runtime": runtime_aliases,
            "providers": providers,
            "fallbacks": _project_fallbacks(document),
        },
        "routing": routing,
        "mcp": mcp,
        "environment": environment,
        "validation": validation,
        "drift": drift,
        "errors": errors,
    }
