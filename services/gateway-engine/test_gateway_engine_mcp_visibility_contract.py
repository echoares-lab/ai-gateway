"""Executable contract fixtures for C-RT-4 MCP visibility (#602).

These tests intentionally exercise the contract and existing policy seam only;
they do not enable MCP enforcement or implement a local tool host.
"""

from __future__ import annotations

from api.policy_hooks import redact_policy_decision

_CONTRACT_FIXTURE = {
    "http_adapters": [
        {"name": "chat", "route": "POST /v1/chat/completions", "seam": "PolicyHookBoundary.apply"},
        {"name": "responses", "route": "POST /v1/responses", "seam": "PolicyHookBoundary.apply"},
        {"name": "claude", "route": "POST /v1/messages", "seam": "PolicyHookBoundary.apply"},
        {
            "name": "gemini",
            "route": "POST /v1beta/models/{model}:generateContent",
            "seam": "PolicyHookBoundary.apply",
        },
    ],
    "decisions": [
        {"condition": "disabled", "visibility": "unfiltered", "request": "forward"},
        {"condition": "evaluator_unavailable", "visibility": "unfiltered", "request": "forward"},
        {"condition": "evaluator_timeout", "visibility": "unfiltered", "request": "forward"},
        {"condition": "evaluator_error", "visibility": "unfiltered", "request": "forward"},
        {"condition": "malformed_decision", "visibility": "unfiltered", "request": "forward"},
        {"condition": "allowlist", "visibility": "allow_only_known", "request": "filter"},
        {"condition": "denylist", "visibility": "deny_known", "request": "filter"},
        {
            "condition": "unknown_alias",
            "visibility": "never_expose",
            "request": "forward_or_deny_when_proven",
        },
    ],
    "metadata": {
        "allowed_keys": ["allowed_mcp_servers", "denied_mcp_servers", "mcp_visibility_mode"],
        "max_aliases": 128,
        "max_alias_bytes": 128,
        "trace_max_aliases": 32,
    },
    "local_host": {
        "request_bytes": 1048576,
        "response_bytes": 33554432,
        "max_depth": 32,
        "timeout_seconds": 10,
        "requires_non_root": True,
        "network_default": "disabled",
    },
}


def _contract() -> dict:
    return _CONTRACT_FIXTURE


def test_all_http_tool_adapters_share_policy_hook_seam():
    adapters = _contract()["http_adapters"]
    assert {item["name"] for item in adapters} == {"chat", "responses", "claude", "gemini"}
    assert {item["seam"] for item in adapters} == {"PolicyHookBoundary.apply"}
    assert all(item["route"].startswith("POST ") for item in adapters)


def test_decision_fixture_covers_fail_open_and_alias_outcomes():
    decisions = {item["condition"]: item for item in _contract()["decisions"]}
    assert {
        "disabled",
        "evaluator_unavailable",
        "evaluator_timeout",
        "evaluator_error",
        "malformed_decision",
    } <= decisions.keys()
    for condition in (
        "disabled",
        "evaluator_unavailable",
        "evaluator_timeout",
        "evaluator_error",
        "malformed_decision",
    ):
        assert decisions[condition]["visibility"] == "unfiltered"
        assert decisions[condition]["request"] == "forward"
    assert decisions["allowlist"]["request"] == "filter"
    assert decisions["denylist"]["request"] == "filter"
    assert decisions["unknown_alias"]["visibility"] == "never_expose"


def test_metadata_fixture_is_bounded_and_redaction_drops_sensitive_mcp_fields():
    metadata = _contract()["metadata"]
    assert metadata["max_aliases"] == 128
    assert metadata["max_alias_bytes"] == 128
    assert metadata["trace_max_aliases"] == 32
    assert {"allowed_mcp_servers", "denied_mcp_servers", "mcp_visibility_mode"} == set(metadata["allowed_keys"])

    decision = {
        "gate": "allow",
        "rules_applied": ["mcp:allowlist:1"],
        "policy_version": "v1",
        "allowed_mcp_servers": ["mcp-fetch"],
        "denied_mcp_servers": ["mcp-postgres"],
        "mcp_tool_description": "do not log this",
        "prompt": "secret prompt",
        "authorization": "Bearer secret",
        "tenancy": {"workspace": "private"},
        "evaluator_error": "private details",
    }
    redacted = redact_policy_decision(decision)
    assert redacted == {"gate": "allow", "rules_applied": ["mcp:allowlist:1"], "policy_version": "v1"}
    assert not any(key in redacted for key in ("allowed_mcp_servers", "denied_mcp_servers", "prompt", "authorization"))


def test_local_host_fixture_requires_isolation_and_hard_bounds():
    host = _contract()["local_host"]
    assert host["requires_non_root"] is True
    assert host["network_default"] == "disabled"
    assert host["request_bytes"] == 1 * 1024 * 1024
    assert host["response_bytes"] == 32 * 1024 * 1024
    assert host["max_depth"] == 32
    assert host["timeout_seconds"] == 10
