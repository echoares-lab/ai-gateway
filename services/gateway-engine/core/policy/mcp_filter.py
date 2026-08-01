"""Bounded MCP tool filtering for the opt-in HTTP visibility child."""

from __future__ import annotations

import copy
import os
from typing import Any

MAX_ALIASES = 128
MAX_ALIAS_BYTES = 128


class McpVisibilityDenied(Exception):
    """A request contains a proven MCP alias outside its effective visibility."""


def _bounded_aliases(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    aliases: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        alias = item.strip()
        if not alias or len(alias.encode("utf-8")) > MAX_ALIAS_BYTES or alias in aliases:
            continue
        aliases.append(alias)
        if len(aliases) >= MAX_ALIASES:
            break
    return aliases


def registered_aliases() -> set[str]:
    """Read the bounded alias registry supplied by the LiteLLM deployment."""
    raw = os.environ.get("MCP_REGISTERED_SERVERS", "")
    return set(_bounded_aliases([item.strip() for item in raw.split(",")]))


def _explicit_alias(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def tool_mcp_alias(tool: Any, *, known_aliases: set[str]) -> str | None:
    """Return a proven MCP alias, never inferring from an arbitrary description."""
    if not isinstance(tool, dict):
        return None
    for source in (tool, tool.get("function"), tool.get("metadata")):
        if not isinstance(source, dict):
            continue
        for key in ("mcp_server", "mcp_server_alias", "server_alias"):
            alias = _explicit_alias(source.get(key))
            if alias:
                return alias
    function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
    name = function.get("name") if isinstance(function, dict) else None
    if not isinstance(name, str):
        return None
    for alias in sorted(known_aliases, key=len, reverse=True):
        if name.startswith(f"mcp__{alias}__") or name.startswith(f"{alias}/") or name.startswith(f"{alias}__"):
            return alias
    return None


def apply_mcp_visibility(body: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Return a filtered copy of tool-bearing body for a valid allow decision."""
    allowed = _bounded_aliases(decision.get("allowed_mcp_servers"))
    denied = _bounded_aliases(decision.get("denied_mcp_servers"))
    if decision.get("allowed_mcp_servers") is None and not denied:
        return body

    known = registered_aliases() | set(allowed) | set(denied)
    allowed_set = set(allowed) if decision.get("allowed_mcp_servers") is not None else None
    denied_set = set(denied)
    filtered = copy.deepcopy(body)
    tools = filtered.get("tools")
    if isinstance(tools, list):
        kept: list[Any] = []
        for tool in tools:
            alias = tool_mcp_alias(tool, known_aliases=known)
            if alias is None:
                kept.append(tool)
            elif allowed_set is not None and alias not in allowed_set:
                continue
            elif alias in denied_set:
                continue
            else:
                kept.append(tool)
        filtered["tools"] = kept
    return filtered


def has_denied_invocation(body: dict[str, Any], decision: dict[str, Any]) -> bool:
    """Detect a proven denied MCP call in prior tool-chain messages."""
    allowed = _bounded_aliases(decision.get("allowed_mcp_servers"))
    denied = set(_bounded_aliases(decision.get("denied_mcp_servers")))
    if decision.get("allowed_mcp_servers") is None and not denied:
        return False
    known = registered_aliases() | set(allowed) | denied
    allowed_set = set(allowed) if decision.get("allowed_mcp_servers") is not None else None
    messages = body.get("messages")
    if not isinstance(messages, list):
        messages = body.get("input") if isinstance(body.get("input"), list) else []
    for message in messages:
        if not isinstance(message, dict):
            continue
        candidates: list[Any] = [message]
        calls = message.get("tool_calls")
        if isinstance(calls, list):
            candidates.extend(calls)
        for candidate in candidates:
            alias = tool_mcp_alias(candidate, known_aliases=known)
            if alias is not None and ((allowed_set is not None and alias not in allowed_set) or alias in denied):
                return True
    return False


def metadata_decision(decision: dict[str, Any], *, enabled: bool) -> dict[str, Any]:
    """Return a copy safe to place in upstream metadata."""
    safe = dict(decision)
    if not enabled:
        safe.pop("allowed_mcp_servers", None)
        safe.pop("denied_mcp_servers", None)
        safe.pop("mcp_visibility_mode", None)
        return safe
    if "allowed_mcp_servers" in safe:
        allowed = _bounded_aliases(safe.get("allowed_mcp_servers"))
        safe["allowed_mcp_servers"] = allowed if safe.get("allowed_mcp_servers") is not None else None
    if "denied_mcp_servers" in safe:
        safe["denied_mcp_servers"] = _bounded_aliases(safe.get("denied_mcp_servers"))
    if safe.get("allowed_mcp_servers") is not None:
        safe["mcp_visibility_mode"] = "allowlist"
    elif safe.get("denied_mcp_servers"):
        safe["mcp_visibility_mode"] = "denylist"
    return safe


__all__ = [
    "MAX_ALIASES",
    "MAX_ALIAS_BYTES",
    "McpVisibilityDenied",
    "apply_mcp_visibility",
    "has_denied_invocation",
    "metadata_decision",
    "registered_aliases",
    "tool_mcp_alias",
]
