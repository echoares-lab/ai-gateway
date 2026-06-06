"""Unit tests for policy-engine admin trace in /admin/status (issue 38-15)."""

import json
import os
import sys
import unittest
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import main as t


def _reset_policy_trace() -> None:
    t._policy_trace.evaluate_ms = None
    t._policy_trace.evaluated_at = None
    t._policy_trace.decision = None
    t._policy_trace.error = None
    t._policy_version_hint = None


class TestPolicyDecisionRedaction(unittest.TestCase):
    def test_redacts_session_key(self):
        sample = t._redact_policy_decision_for_admin(
            {
                "gate": "allow",
                "session_key": "sess-secret-abc",
                "rules_applied": ["repo:affinity"],
            }
        )
        assert sample["session_key"] == "[redacted]"
        assert "sess-secret" not in json.dumps(sample)

    def test_quota_fields_only_when_quota_aware(self):
        without = t._redact_policy_decision_for_admin(
            {"gate": "allow", "quota_aware_mode": False, "deprioritized_credentials": ["cred-x"]}
        )
        assert "deprioritized_credentials" not in without

        with_quota = t._redact_policy_decision_for_admin(
            {
                "gate": "allow",
                "quota_aware_mode": True,
                "deprioritized_credentials": ["cred-a", "cred-b"],
                "rules_applied": ["quota:deprioritize"],
            }
        )
        assert with_quota["deprioritized_credentials"] == ["cred-a", "cred-b"]
        assert with_quota["rules_applied"] == ["quota:deprioritize"]


class TestAdminPolicyEngineData(unittest.TestCase):
    def setUp(self):
        _reset_policy_trace()
        self._env_patch = patch.dict(
            os.environ,
            {"ADMIN_POLICY_TRACE_ENABLED": "true", "POLICY_ENGINE_ENABLED": "false"},
            clear=False,
        )
        self._env_patch.start()
        t.ADMIN_POLICY_TRACE_ENABLED = True
        t.POLICY_ENGINE_ENABLED = False

    def tearDown(self):
        self._env_patch.stop()
        _reset_policy_trace()

    def test_trace_disabled_omits_section(self):
        t.ADMIN_POLICY_TRACE_ENABLED = False
        assert t._build_admin_policy_engine_data(redis_connected=None, policy_version=None) is None

    def test_trace_includes_enabled_and_last_evaluate_ms(self):
        t._record_policy_trace(
            {"gate": "allow", "policy_version": "v0-stub", "rules_applied": ["stub"]},
            12.34,
        )
        data = t._build_admin_policy_engine_data(redis_connected=True, policy_version="v0-stub")
        assert data is not None
        assert data["enabled"] is False
        assert data["trace_enabled"] is True
        assert data["last_evaluate_ms"] == 12.34
        assert data["policy_version"] == "v0-stub"
        assert data["redis_connected"] is True
        assert data["last_decision"]["gate"] == "allow"


class TestAdminRoutingPanelPolicyTrace(unittest.TestCase):
    def setUp(self):
        _reset_policy_trace()
        t.ADMIN_POLICY_TRACE_ENABLED = True

    def tearDown(self):
        _reset_policy_trace()

    def test_routing_panel_includes_policy_engine_subsection(self):
        policy_engine = {
            "enabled": False,
            "trace_enabled": True,
            "last_evaluate_ms": 8.0,
            "redis_connected": None,
            "policy_version": None,
        }
        panel = t._admin_routing_panel({}, "", [], policy_engine=policy_engine)
        assert panel["data"]["policy_engine"] == policy_engine


@pytest.mark.asyncio
async def test_admin_status_includes_policy_engine_trace():
    from fastapi.testclient import TestClient

    _reset_policy_trace()
    t.ADMIN_POLICY_TRACE_ENABLED = True
    t._record_policy_trace(
        {
            "gate": "allow",
            "quota_aware_mode": True,
            "deprioritized_credentials": ["cred-1"],
            "session_key": "sess-live",
            "rules_applied": ["quota:aware"],
            "policy_version": "v0-stub",
        },
        5.5,
    )

    async def fake_visible():
        return ["claude-sonnet-4-6"], []

    async def fake_metrics():
        return "", []

    async def fake_connectivity():
        return True, "v0-stub"

    with patch.object(t, "_admin_load_litellm_config", return_value=({"model_list": []}, [])), patch.object(
        t, "_admin_fetch_visible_models", fake_visible
    ), patch.object(t, "_admin_fetch_metrics_text", fake_metrics), patch.object(
        t, "_admin_policy_engine_connectivity", fake_connectivity
    ), patch.object(t, "_admin_run_readonly_command", lambda *a, **k: ("", [])):
        client = TestClient(t.app)
        resp = client.get("/admin/status")

    assert resp.status_code == 200
    routing = resp.json()["panels"]["routing"]["data"]
    trace = routing["policy_engine"]
    assert trace["enabled"] is False
    assert trace["last_evaluate_ms"] == 5.5
    assert trace["last_decision"]["quota_aware_mode"] is True
    assert trace["last_decision"]["deprioritized_credentials"] == ["cred-1"]
    assert trace["last_decision"]["session_key"] == "[redacted]"
    raw = resp.text
    assert "sess-live" not in raw


if __name__ == "__main__":
    unittest.main()
