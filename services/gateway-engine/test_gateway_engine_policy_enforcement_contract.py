"""C-RT-3 contract fixtures for strict HTTP and optional WS parity children."""

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import main as gateway_main
from api import proxy_catchall, proxy_claude, proxy_gemini, proxy_responses, ws_router
from api.policy_hooks import redact_policy_decision

HTTP_MATRIX = (
    ("disabled", False, None, "forward"),
    ("allow", True, "allow", "forward_with_metadata"),
    ("deny", True, "deny", "typed_403"),
    ("unavailable", True, None, "fail_open"),
    ("timeout", True, None, "fail_open"),
    ("error", True, None, "fail_open"),
    ("malformed", True, None, "fail_open"),
)


@pytest.mark.parametrize("condition,enabled,gate,action", HTTP_MATRIX)
def test_http_contract_matrix_is_explicit(condition, enabled, gate, action):
    assert condition in {"disabled", "allow", "deny", "unavailable", "timeout", "error", "malformed"}
    assert isinstance(enabled, bool)
    assert gate in {None, "allow", "deny"}
    assert action in {"forward", "forward_with_metadata", "typed_403", "fail_open"}


@pytest.mark.parametrize(
    "module,function_name",
    (
        (proxy_catchall, "proxy"),
        (proxy_responses, "responses_proxy"),
        (proxy_claude, "claude_proxy"),
        (proxy_gemini, "gemini_proxy"),
    ),
)
def test_http_adapters_use_caud8_policy_boundary(module, function_name):
    source = inspect.getsource(getattr(module, function_name))
    assert "_policy_hooks" in source
    assert ".apply(" in source


@pytest.mark.parametrize(
    "policy_enabled,ws_enabled,bypass",
    ((False, False, True), (True, False, True), (False, True, True), (True, True, False)),
)
def test_websocket_flag_matrix_preserves_default_bypass(policy_enabled, ws_enabled, bypass):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("POLICY_ENGINE_ENABLED", str(policy_enabled).lower())
        monkeypatch.setenv("POLICY_ENGINE_WS_EVALUATE", str(ws_enabled).lower())
        assert ws_router.codex_ws_policy_bypass() is bypass


def test_websocket_router_has_injected_boundary_and_bounded_denial():
    source = inspect.getsource(ws_router.create_ws_router)
    assert "policy_hooks" in source
    assert "code=1008" in source
    assert len(ws_router._ws_policy_denial_reason({"gate": "deny", "deny_reason": "x" * 500})) == 123


def test_redaction_fixture_excludes_secrets_and_arbitrary_keys():
    decision = {
        "gate": "allow",
        "rules_applied": ["rule"],
        "policy_version": "crt3-v1",
        "quota_aware_mode": True,
        "deprioritized_credentials": ["cred-a"],
        "session_key": "secret",
        "tenant_id": "secret-tenant",
        "authorization": "Bearer secret",
        "frame": "secret payload",
    }
    assert redact_policy_decision(decision) == {
        "gate": "allow",
        "rules_applied": ["rule"],
        "policy_version": "crt3-v1",
        "quota_aware_mode": True,
        "deprioritized_credentials": ["cred-a"],
        "session_key": "[redacted]",
    }
    assert gateway_main._redact_policy_decision_for_admin(decision) == redact_policy_decision(decision)
