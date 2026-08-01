"""Unit tests for opt-in HTTP MCP visibility filtering (C-RT-4 #605)."""

from __future__ import annotations

from core.policy.mcp_filter import apply_mcp_visibility, has_denied_invocation, metadata_decision, tool_mcp_alias


def _tool(name: str, **metadata):
    return {"type": "function", "function": {"name": name}, **metadata}


def test_explicit_alias_is_proven_and_arbitrary_name_is_not_guessed():
    assert tool_mcp_alias(_tool("search", mcp_server="mcp-git"), known_aliases=set()) == "mcp-git"
    assert tool_mcp_alias(_tool("mcp__mcp-git__search"), known_aliases={"mcp-git"}) == "mcp-git"
    assert tool_mcp_alias(_tool("mcp__unknown__search"), known_aliases={"mcp-git"}) is None


def test_allowlist_keeps_ordinary_tools_and_only_allowed_mcp_aliases():
    body = {
        "tools": [
            _tool("ordinary", description="client-defined"),
            _tool("search", mcp_server="mcp-git"),
            _tool("fetch", mcp_server="mcp-fetch"),
        ]
    }
    filtered = apply_mcp_visibility(body, {"allowed_mcp_servers": ["mcp-git"], "denied_mcp_servers": []})
    assert [tool["function"]["name"] for tool in filtered["tools"]] == ["ordinary", "search"]
    assert len(body["tools"]) == 3


def test_denylist_filters_registered_name_and_explicit_alias_idempotently(monkeypatch):
    monkeypatch.setenv("MCP_REGISTERED_SERVERS", "mcp-git,mcp-fetch")
    body = {
        "tools": [
            _tool("mcp__mcp-git__search"),
            _tool("fetch", mcp_server="mcp-fetch"),
            _tool("ordinary"),
        ]
    }
    decision = {"allowed_mcp_servers": None, "denied_mcp_servers": ["mcp-git"]}
    filtered = apply_mcp_visibility(body, decision)
    assert [tool["function"]["name"] for tool in filtered["tools"]] == ["fetch", "ordinary"]
    assert apply_mcp_visibility(filtered, decision) == filtered


def test_disabled_visibility_returns_same_body():
    body = {"tools": [_tool("mcp__mcp-git__search")]}
    assert apply_mcp_visibility(body, {"allowed_mcp_servers": None, "denied_mcp_servers": []}) is body


def test_missing_or_malformed_decision_fails_open():
    body = {"tools": [_tool("search", mcp_server="mcp-fetch")]}
    assert apply_mcp_visibility(body, {}) is body


def test_denied_invocation_is_detected_only_for_proven_alias(monkeypatch):
    monkeypatch.setenv("MCP_REGISTERED_SERVERS", "mcp-git,mcp-fetch")
    decision = {"allowed_mcp_servers": ["mcp-git"], "denied_mcp_servers": []}
    assert has_denied_invocation(
        {"messages": [{"role": "assistant", "tool_calls": [{"function": {"name": "mcp__mcp-fetch__search"}}]}]},
        decision,
    )
    assert not has_denied_invocation(
        {"messages": [{"role": "assistant", "tool_calls": [{"function": {"name": "ordinary_tool"}}]}]}, decision
    )


def test_metadata_decision_is_bounded_and_feature_off_drops_mcp_fields():
    decision = {"gate": "allow", "allowed_mcp_servers": ["mcp-git"] * 200, "denied_mcp_servers": ["mcp-fetch"]}
    safe = metadata_decision(decision, enabled=True)
    assert len(safe["allowed_mcp_servers"]) == 1
    assert safe["mcp_visibility_mode"] == "allowlist"
    assert "allowed_mcp_servers" not in metadata_decision(decision, enabled=False)
