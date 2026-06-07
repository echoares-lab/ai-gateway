"""MCP server visibility resolver (issue 38-20, phase 5b).

Resolves ``policy_json.mcp`` from layered policy profiles and produces
``allowed_mcp_servers`` / ``denied_mcp_servers`` for LiteLLM metadata injection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from core.policy.schemas import PolicyProfile

DEFAULT_MODE = "denylist"


@dataclass(frozen=True)
class McpVisibilityResult:
    allowed_mcp_servers: list[str] | None = None
    denied_mcp_servers: list[str] = field(default_factory=list)
    rules_applied: list[str] = field(default_factory=list)


def _mcp_section(policy_json: dict) -> dict | None:
    mcp = policy_json.get("mcp")
    if isinstance(mcp, dict) and mcp:
        return mcp
    legacy = policy_json.get("mcp_allowlist")
    if legacy:
        return {"mode": "allowlist", "servers": list(legacy)}
    return None


def extract_mcp_config(profiles: list[PolicyProfile]) -> dict | None:
    """Return the most-specific MCP policy (profiles load org → repo)."""
    effective: dict | None = None
    for profile in profiles:
        section = _mcp_section(profile.policy_json)
        if section is not None:
            effective = section
    return effective


def _parse_registered(registered: list[str] | str | None) -> list[str] | None:
    if registered is None:
        env = os.environ.get("MCP_REGISTERED_SERVERS", "").strip()
        if not env:
            return None
        return [item.strip() for item in env.split(",") if item.strip()]
    if isinstance(registered, str):
        return [item.strip() for item in registered.split(",") if item.strip()]
    return list(registered)


def resolve_mcp_visibility(
    profiles: list[PolicyProfile],
    *,
    registered_mcp_servers: list[str] | str | None = None,
) -> McpVisibilityResult:
    """Resolve effective MCP visibility for layered tenancy profiles."""
    config = extract_mcp_config(profiles)
    if config is None:
        return McpVisibilityResult()

    mode = str(config.get("mode", DEFAULT_MODE)).lower()
    raw_servers = config.get("servers") or []
    if not isinstance(raw_servers, list):
        raw_servers = []
    servers = [str(item) for item in raw_servers]

    if mode == "allowlist":
        return McpVisibilityResult(
            allowed_mcp_servers=servers,
            rules_applied=[f"mcp:allowlist:{len(servers)}"],
        )

    if not servers:
        return McpVisibilityResult()

    registered = _parse_registered(registered_mcp_servers)
    if registered is not None:
        denied_set = set(servers)
        allowed = [alias for alias in registered if alias not in denied_set]
        hidden = sorted(alias for alias in registered if alias in denied_set)
        rules = [f"mcp:denylist:{len(servers)}"]
        if hidden:
            rules.append(f"mcp:hidden:{','.join(hidden)}")
        return McpVisibilityResult(
            allowed_mcp_servers=allowed,
            denied_mcp_servers=servers,
            rules_applied=rules,
        )

    return McpVisibilityResult(
        denied_mcp_servers=servers,
        rules_applied=[f"mcp:denylist:{len(servers)}"],
    )
