import json
import os

# Ensure we can import from the local directory
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(__file__))

import prober
from notifier import send_slack_alert


class TestSlackNotifier(unittest.TestCase):
    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "http://mock-slack-webhook"})
    def test_send_slack_alert_success(self, mock_urlopen):
        # Arrange
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Act
        res = send_slack_alert(
            event="credential_critical",
            credential_id="cred-test-01",
            provider="anthropic",
            reason="401 Unauthorized",
            timestamp="2026-06-02T13:45:00Z",
        )

        # Assert
        self.assertTrue(res)
        mock_urlopen.assert_called_once()
        args, kwargs = mock_urlopen.call_args
        req = args[0]

        # Verify request properties
        self.assertEqual(req.full_url, "http://mock-slack-webhook")
        self.assertEqual(req.headers["Content-type"], "application/json")

        # Verify request data
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["event"], "credential_critical")
        self.assertEqual(payload["credential_id"], "cred-test-01")
        self.assertEqual(payload["provider"], "anthropic")
        self.assertEqual(payload["reason"], "401 Unauthorized")
        self.assertEqual(payload["timestamp"], "2026-06-02T13:45:00Z")

    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "http://mock-slack-webhook"})
    def test_send_slack_alert_http_error(self, mock_urlopen):
        # Arrange
        mock_urlopen.side_effect = Exception("HTTP 500 Internal Server Error")

        # Act
        res = send_slack_alert(
            event="credential_critical", credential_id="cred-test-01", provider="anthropic", reason="401 Unauthorized"
        )

        # Assert
        self.assertFalse(res)

    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {}, clear=True)
    def test_send_slack_alert_missing_webhook_url(self, mock_urlopen):
        # Act
        res = send_slack_alert(
            event="credential_critical", credential_id="cred-test-01", provider="anthropic", reason="401 Unauthorized"
        )

        # Assert
        self.assertFalse(res)
        mock_urlopen.assert_not_called()


class TestProberTransitions(unittest.TestCase):
    @patch("prober.get_cliproxy_auth_files")
    @patch("prober.send_slack_alert")
    @patch("psycopg2.connect")
    def test_sync_inventory_transitions(self, mock_connect, mock_send_alert, mock_get_files):
        # Arrange
        mock_get_files.return_value = [
            {
                "id": "cred-1",
                "provider": "anthropic",
                "label": "Test Key",
                "status": "error",
                "auth_index": "sha256-fingerprint",
                "failed": 3,
                "status_message": "401 Unauthorized",
            },
            {
                "id": "cred-2",
                "provider": "openai",
                "label": "Test Key 2",
                "status": "active",
                "auth_index": "sha256-fingerprint-2",
                "failed": 0,
                "status_message": "",
            },
            {
                "id": "cred-3",
                "provider": "gemini",
                "label": "Test Key 3",
                "status": "active",
                "auth_index": "sha256-fingerprint-3",
                "failed": 0,
                "status_message": "",
            },
        ]

        # Mock database connection and cursor
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur

        # Existing statuses in database:
        # cred-1 was HEALTHY (now CRITICAL -> should alert)
        # cred-2 was CRITICAL (now HEALTHY -> should alert recovery)
        # cred-3 was HEALTHY (now HEALTHY -> should NOT alert)
        mock_cur.fetchall.return_value = [("cred-1", "HEALTHY"), ("cred-2", "CRITICAL"), ("cred-3", "HEALTHY")]

        # Act
        prober.sync_inventory()

        # Assert
        # Check alerts sent
        self.assertEqual(mock_send_alert.call_count, 2)

        # Alert 1: cred-1 transitioned to CRITICAL
        mock_send_alert.assert_any_call("credential_critical", "cred-1", "anthropic", "401 Unauthorized")

        # Alert 2: cred-2 transitioned to HEALTHY (recovery)
        mock_send_alert.assert_any_call(
            "credential_healthy", "cred-2", "openai", "Status changed from CRITICAL to HEALTHY"
        )


if __name__ == "__main__":
    unittest.main()
