import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(__file__))

from credential_probe import (
    build_inventory_payload,
    build_policy_engine_event_payload,
    build_transition_payload,
    compute_cool_down_until,
    map_auth_file_status,
    normalize_provider,
    should_emit_transition,
)


class TestCredentialProbeHelpers(unittest.TestCase):
    def test_normalize_provider_maps_cliproxy_names(self):
        self.assertEqual(normalize_provider("antigravity"), "gemini")
        self.assertEqual(normalize_provider("claude"), "anthropic")
        self.assertEqual(normalize_provider("codex"), "openai")
        self.assertEqual(normalize_provider("gemini-cli"), "gemini")
        self.assertEqual(normalize_provider("anthropic"), "anthropic")
        self.assertEqual(normalize_provider(None), "unknown")

    def test_map_auth_file_status_preserves_existing_mapping(self):
        self.assertEqual(map_auth_file_status({"disabled": True, "status": "active"}), "SUSPENDED")
        self.assertEqual(map_auth_file_status({"status": "active"}), "HEALTHY")
        self.assertEqual(map_auth_file_status({"status": "error"}), "CRITICAL")
        self.assertEqual(map_auth_file_status({"status": "unknown"}), "DEGRADED")

    def test_compute_cooldown_uses_status_specific_duration(self):
        now = datetime(2026, 6, 6, 13, 0, tzinfo=timezone.utc)
        self.assertIsNone(compute_cool_down_until("HEALTHY", now=now))
        self.assertEqual(
            compute_cool_down_until("DEGRADED", now=now, degraded_cooldown_sec=30),
            now + timedelta(seconds=30),
        )
        self.assertEqual(
            compute_cool_down_until("CRITICAL", now=now, critical_cooldown_sec=90),
            now + timedelta(seconds=90),
        )

    def test_build_inventory_payload_matches_db_upsert_fields(self):
        now = datetime(2026, 6, 6, 13, 0, tzinfo=timezone.utc)
        payload = build_inventory_payload(
            {
                "id": "file-1.json",
                "provider": "antigravity",
                "account": "acct",
                "auth_index": "fp",
                "status": "error",
                "failed": 3,
                "status_message": "401 Unauthorized",
                "recent_requests": [{"status": 401}],
                "updated_at": "2026-06-06T12:59:00Z",
            },
            now=now,
            critical_cooldown_sec=120,
        )

        self.assertEqual(payload["credential_id"], "file-1.json")
        self.assertEqual(payload["provider"], "gemini")
        self.assertEqual(payload["label"], "acct")
        self.assertEqual(payload["key_fingerprint"], "fp")
        self.assertEqual(payload["status"], "CRITICAL")
        self.assertEqual(payload["cool_down_until"], now + timedelta(seconds=120))
        self.assertEqual(payload["consecutive_failures"], 3)
        self.assertEqual(
            payload["metadata"],
            {
                "recent_requests": [{"status": 401}],
                "status_message": "401 Unauthorized",
                "updated_at": "2026-06-06T12:59:00Z",
            },
        )

    def test_transition_payload_preserves_routing_exclusion_shape(self):
        cooldown = datetime(2026, 6, 6, 13, 1, tzinfo=timezone.utc)
        payload = build_transition_payload(
            credential_id="cred-1",
            provider="anthropic",
            old_status="HEALTHY",
            new_status="CRITICAL",
            status_message="401 Unauthorized",
            cool_down_until=cooldown,
        )

        self.assertTrue(should_emit_transition("HEALTHY", "CRITICAL"))
        self.assertFalse(should_emit_transition(None, "HEALTHY"))
        self.assertEqual(payload["previous_status"], "HEALTHY")
        self.assertEqual(payload["reason"], "401 Unauthorized")
        self.assertEqual(payload["cool_down_until"], cooldown)
        self.assertEqual(payload["slack_event"], "credential_critical")

    def test_policy_engine_event_payload_shape(self):
        timestamp = datetime(2026, 6, 6, 13, 0, tzinfo=timezone.utc)
        cooldown = datetime(2026, 6, 6, 13, 1, tzinfo=timezone.utc)
        payload = build_policy_engine_event_payload(
            "cred-1",
            "anthropic",
            "HEALTHY",
            "CRITICAL",
            reason="401 Unauthorized",
            cool_down_until=cooldown,
            timestamp=timestamp,
        )

        self.assertEqual(
            payload,
            {
                "credential_id": "cred-1",
                "provider": "anthropic",
                "previous_status": "HEALTHY",
                "new_status": "CRITICAL",
                "timestamp": "2026-06-06T13:00:00+00:00",
                "reason": "401 Unauthorized",
                "cool_down_until": "2026-06-06T13:01:00+00:00",
            },
        )


if __name__ == "__main__":
    unittest.main()
