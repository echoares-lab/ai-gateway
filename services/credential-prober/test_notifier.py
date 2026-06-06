import json
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(__file__))

import prober
from notifier import notify_policy_engine, send_slack_alert


class TestSlackNotifier(unittest.TestCase):
    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "http://mock-slack-webhook"})
    def test_send_slack_alert_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response
        self.assertTrue(send_slack_alert("credential_critical", "cred-1", "anthropic", "401", timestamp="2026-06-02T13:45:00Z"))

    @patch.dict(os.environ, {}, clear=True)
    def test_send_slack_alert_missing_webhook_url(self):
        self.assertFalse(send_slack_alert("credential_critical", "cred-1", "anthropic", "401"))


class TestPolicyEngineNotifier(unittest.TestCase):
    @patch("urllib.request.urlopen")
    @patch.dict(os.environ, {"TRANSLATOR_URL": "http://translator:4000"})
    def test_notify_policy_engine_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 202
        mock_urlopen.return_value.__enter__.return_value = mock_response
        cooldown = datetime(2026, 6, 5, 13, 0, tzinfo=timezone.utc)
        self.assertTrue(notify_policy_engine("cred-1", "anthropic", "HEALTHY", "CRITICAL", cool_down_until=cooldown))


class TestProberSync(unittest.TestCase):
    @patch("prober.notify_policy_engine")
    @patch("prober.send_slack_alert")
    @patch("psycopg2.connect")
    @patch("prober.get_cliproxy_auth_files")
    def test_sync_inventory_critical_sets_cooldown(self, mock_get_files, mock_connect, _slack, mock_policy):
        mock_get_files.return_value = [{
            "id": "file-1.json", "provider": "anthropic", "label": "acct", "auth_index": "fp",
            "status": "error", "failed": 3, "status_message": "401 Unauthorized", "recent_requests": [],
        }]
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn
        mock_cur.fetchall.return_value = []
        prober.sync_inventory()
        sql_query, params = mock_cur.execute.call_args[0]
        self.assertIn("cool_down_until", sql_query)
        self.assertEqual(params[4], "CRITICAL")
        mock_policy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
