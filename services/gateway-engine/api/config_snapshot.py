"""Pure, bounded construction of the unified configuration snapshot."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import yaml
from core.model_registry import is_canonical_model_id, provider_of

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
_CREDENTIAL_LIKE_ALIAS = re.compile(
    r"^(?:gh[opsur]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{40,255}|"
    r"xox[baprs]-[A-Za-z0-9-]{32,255}|AKIA[A-Z0-9]{16}|"
    r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,255})$",
    re.I,
)


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
    public_family = provider_of(model_name)
    if public_family in _SAFE_PROVIDER_FAMILIES:
        return public_family
    candidate = params.get("model") if isinstance(params, Mapping) else None
    for value in (candidate,):
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
            references.update(reference for reference in ENV_REFERENCE.findall(value) if len(reference) <= MAX_STRING)

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
    canonical = json.dumps(
        _sanitize_for_digest(projection),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_status(value: object) -> str:
    return value if isinstance(value, str) and value in _SOURCE_STATUSES else "unavailable"


def _safe_alias(value: object) -> str | None:
    """Return a public model/server token, rejecting instead of redacting unsafe input."""
    if not isinstance(value, str) or len(value) > MAX_STRING or not is_canonical_model_id(value):
        return None
    if _CREDENTIAL_LIKE_ALIAS.fullmatch(value):
        return None
    return value


def _normalised_aliases(
    values: tuple[str, ...] | None,
    *,
    strip_public_prefix: bool = False,
) -> tuple[list[str], bool]:
    aliases: set[str] = set()
    invalid = False
    for value in values or ():
        if not isinstance(value, str):
            invalid = True
            continue
        if strip_public_prefix and value.startswith("AI-Gateway:"):
            value = value[len("AI-Gateway:") :]
        alias = _safe_alias(value)
        if alias:
            aliases.add(alias)
        else:
            invalid = True
    return sorted(aliases)[:MAX_ENTRIES], invalid


def _safe_router_value(value: object) -> tuple[bool | int | float | str | None, bool]:
    if value is None or isinstance(value, (bool, int)):
        return value, True
    if isinstance(value, float):
        return (value, True) if math.isfinite(value) else (None, False)
    if isinstance(value, str):
        safe = _safe_alias(value)
        return safe, safe is not None
    return None, False


def _litellm_setting(document: Mapping[str, Any], name: str) -> object:
    settings = document.get("litellm_settings")
    if isinstance(settings, Mapping) and name in settings:
        return settings.get(name)
    return document.get(name)


def _project_mcp(document: Mapping[str, Any]) -> tuple[list[dict[str, str]], bool]:
    servers = _litellm_setting(document, "mcp_servers")
    if servers is None:
        return [], False
    if not isinstance(servers, Mapping):
        return [], True
    projected: dict[str, str] = {}
    invalid = False
    for alias, server in servers.items():
        safe_alias = _safe_alias(alias)
        if not safe_alias or not isinstance(server, Mapping):
            invalid = True
            continue
        transport = server.get("transport")
        if transport is None and isinstance(server.get("command"), str):
            transport = "stdio"
        if not isinstance(transport, str) or transport.lower() not in _SAFE_MCP_TRANSPORTS:
            invalid = True
            continue
        normalized = transport.lower()
        projected[safe_alias] = min(projected.get(safe_alias, normalized), normalized)
    return (
        [{"alias": alias, "transport": transport} for alias, transport in sorted(projected.items())[:MAX_ENTRIES]],
        invalid,
    )


def _project_fallbacks(document: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    raw_fallbacks = _litellm_setting(document, "fallbacks")
    pairs: dict[str, set[str]] = {}
    if raw_fallbacks is None:
        return [], False
    if not isinstance(raw_fallbacks, list):
        return [], True
    invalid = False
    for entry in raw_fallbacks:
        if not isinstance(entry, Mapping):
            invalid = True
            continue
        for source, targets in entry.items():
            safe_source = _safe_alias(source)
            if not safe_source or not isinstance(targets, (list, tuple)):
                invalid = True
                continue
            safe_targets = set()
            for target in targets:
                alias = _safe_alias(target)
                if alias:
                    safe_targets.add(alias)
                else:
                    invalid = True
            if safe_targets:
                pairs.setdefault(safe_source, set()).update(safe_targets)
    return (
        [
            {"from": source, "to": sorted(targets)[:MAX_ENTRIES]}
            for source, targets in sorted(pairs.items())[:MAX_ENTRIES]
        ],
        invalid,
    )


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


def _status_for_error_code(code: str) -> str:
    return {"source_missing": "missing", "source_invalid": "invalid"}.get(code, "unavailable")


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
    configured_aliases_invalid = False
    for entry in model_list:
        if not isinstance(entry, Mapping):
            configured_aliases_invalid = True
            continue
        alias = _safe_alias(entry.get("model_name"))
        if not alias:
            configured_aliases_invalid = True
            continue
        configured.add(alias)
        params = entry.get("litellm_params")
        family = _safe_provider_family(alias, params if isinstance(params, Mapping) else {})
        provider_by_alias[alias] = min(provider_by_alias.get(alias, family), family)

    configured_aliases = sorted(configured)[:MAX_ENTRIES]
    registry_aliases, registry_aliases_invalid = _normalised_aliases(inputs.registry_model_ids)
    runtime_aliases, runtime_aliases_invalid = _normalised_aliases(
        inputs.runtime_model_ids,
        strip_public_prefix=True,
    )
    providers = [
        {"alias": alias, "family": provider_by_alias[alias]}
        for alias in configured_aliases
        if alias in provider_by_alias
    ]
    routing: dict[str, bool | int | float | str] = {}
    router_invalid = False
    router_settings = document.get("router_settings")
    if router_settings is not None and not isinstance(router_settings, Mapping):
        router_invalid = True
    if isinstance(router_settings, Mapping):
        for setting in SAFE_ROUTER_SETTINGS:
            if setting not in router_settings:
                continue
            safe_value, valid = _safe_router_value(router_settings.get(setting))
            if not valid:
                router_invalid = True
            elif safe_value is not None:
                routing[setting] = safe_value
    mcp, mcp_invalid = _project_mcp(document)
    fallbacks, fallbacks_invalid = _project_fallbacks(document)
    litellm_aliases_invalid = configured_aliases_invalid or mcp_invalid or fallbacks_invalid
    environment_references = _extract_environment_references(document)
    environment = [{"name": name, "present": name in inputs.environment} for name in environment_references]
    validation = [
        {"id": "deployed-config", "status": "pass" if document_valid else "fail"},
        {
            "id": "environment-references",
            "status": "pass" if all(item["present"] for item in environment) else "warn",
        },
        {
            "id": "source-aliases",
            "status": "fail"
            if litellm_aliases_invalid or registry_aliases_invalid or runtime_aliases_invalid
            else "pass",
        },
        {"id": "router-settings", "status": "fail" if router_invalid else "pass"},
    ]

    statuses = {
        "litellm-config": litellm_status,
        "model-registry": registry_status,
        "runtime-visible-models": runtime_status,
    }
    source_errors: dict[str, str] = {}
    for source, code in inputs.source_errors[:MAX_ENTRIES]:
        if source in statuses and code in _SOURCE_ERROR_CODES:
            source_errors[source] = min(source_errors.get(source, code), code)
    for source, code in source_errors.items():
        statuses[source] = _status_for_error_code(code)
    invalid_sources = {
        source
        for source, invalid in (
            ("litellm-config", litellm_aliases_invalid or router_invalid),
            ("model-registry", registry_aliases_invalid),
            ("runtime-visible-models", runtime_aliases_invalid),
        )
        if invalid
    }
    for source in invalid_sources:
        statuses[source] = "invalid"
        source_errors[source] = min(source_errors.get(source, "source_invalid"), "source_invalid")
    for source, status in statuses.items():
        if status != "ok" and source not in source_errors:
            source_errors[source] = _error_code_for_status(status)

    configured_set = set(configured_aliases)
    registry_set = set(registry_aliases)
    runtime_set = set(runtime_aliases)
    drift_fields = {
        "configured_only": sorted(configured_set - registry_set)[:MAX_ENTRIES],
        "registry_only": sorted(registry_set - configured_set)[:MAX_ENTRIES],
        "runtime_only": sorted(runtime_set - (configured_set | registry_set))[:MAX_ENTRIES],
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
                "fallbacks": fallbacks,
            },
            "routing": routing,
            "mcp": mcp,
            "environment": [item["name"] for item in environment],
        },
        "model-registry": {"model_ids": registry_aliases},
        "runtime-visible-models": {"model_ids": runtime_aliases},
    }
    observed_at = _iso_utc(inputs.generated_at)
    sources = []
    for identifier, kind in _SOURCE_DETAILS:
        source = {
            "id": identifier,
            "kind": kind,
            "status": statuses[identifier],
            "observed_at": observed_at,
        }
        if statuses[identifier] == "ok":
            source["digest"] = _sanitized_projection_digest(source_projections[identifier])
        sources.append(source)
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
            "fallbacks": fallbacks,
        },
        "routing": routing,
        "mcp": mcp,
        "environment": environment,
        "validation": validation,
        "drift": drift,
        "errors": errors,
    }
