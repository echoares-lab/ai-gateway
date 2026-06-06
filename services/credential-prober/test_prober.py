from unittest.mock import MagicMock, patch

import prober


@patch("prober.notify_policy_engine")
@patch("prober.send_slack_alert")
@patch("psycopg2.connect")
@patch("prober.get_cliproxy_auth_files")
def test_sync_inventory_healthy(mock_get_files, mock_connect, _slack, _policy):
    mock_get_files.return_value = [{
        "id": "file-1.json", "provider": "anthropic", "label": "acct", "auth_index": "fp",
        "status": "active", "failed": 0, "status_message": "", "recent_requests": [],
    }]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_connect.return_value = mock_conn
    mock_cur.fetchall.return_value = []
    prober.sync_inventory()
    _, params = mock_cur.execute.call_args[0]
    assert params[4] == "HEALTHY"
    assert params[5] is None


def test_normalize_provider_maps_cliproxy_names():
    assert prober.normalize_provider("antigravity") == "gemini"
    assert prober.normalize_provider("claude") == "anthropic"
    assert prober.normalize_provider("codex") == "openai"
    assert prober.normalize_provider("gemini-cli") == "gemini"
    assert prober.normalize_provider("anthropic") == "anthropic"


@patch("prober.notify_policy_engine")
@patch("prober.send_slack_alert")
@patch("psycopg2.connect")
@patch("prober.get_cliproxy_auth_files")
def test_sync_inventory_maps_provider(mock_get_files, mock_connect, _slack, _policy):
    mock_get_files.return_value = [{
        "id": "file-2.json", "provider": "antigravity", "label": "acct", "auth_index": "fp2",
        "status": "active", "failed": 0, "status_message": "", "recent_requests": [],
    }]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_connect.return_value = mock_conn
    mock_cur.fetchall.return_value = []
    prober.sync_inventory()
    _, params = mock_cur.execute.call_args[0]
    assert params[1] == "gemini"
