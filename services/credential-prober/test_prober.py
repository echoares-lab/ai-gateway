from unittest.mock import MagicMock, patch

import prober


@patch("prober.notify_policy_engine")
@patch("prober.send_slack_alert")
@patch("psycopg2.connect")
@patch("prober.get_cliproxy_auth_files")
def test_sync_inventory_healthy(mock_get_files, mock_connect, _slack, _policy):
    mock_get_files.return_value = [
        {
            "id": "file-1.json",
            "provider": "anthropic",
            "label": "acct",
            "auth_index": "fp",
            "status": "active",
            "failed": 0,
            "status_message": "",
            "recent_requests": [],
        }
    ]
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
    assert prober.normalize_provider("kimi") == "moonshot"


@patch("prober.notify_policy_engine")
@patch("prober.send_slack_alert")
@patch("psycopg2.connect")
@patch("prober.get_cliproxy_auth_files")
def test_sync_inventory_maps_provider(mock_get_files, mock_connect, _slack, _policy):
    mock_get_files.return_value = [
        {
            "id": "file-2.json",
            "provider": "antigravity",
            "label": "acct",
            "auth_index": "fp2",
            "status": "active",
            "failed": 0,
            "status_message": "",
            "recent_requests": [],
        }
    ]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_connect.return_value = mock_conn
    mock_cur.fetchall.return_value = []
    prober.sync_inventory()
    _, params = mock_cur.execute.call_args[0]
    assert params[1] == "gemini"


@patch("prober.notify_policy_engine")
@patch("prober.send_slack_alert")
@patch("psycopg2.connect")
@patch("prober.get_cliproxy_auth_files")
def test_sync_inventory_skips_invalid_before_db_writes(mock_get_files, mock_connect, _slack, _policy):
    mock_get_files.return_value = [
        {
            "id": "valid.json",
            "provider": "anthropic",
            "label": "acct",
            "auth_index": "fp-valid",
            "status": "active",
            "failed": 0,
            "status_message": "",
            "recent_requests": [],
        },
        {
            "id": "runtime-only",
            "provider": "aistudio",
            "runtime_only": True,
            "status": "active",
            "failed": 0,
            "status_message": "",
            "recent_requests": [],
        },
        {
            "provider": "anthropic",
            "label": "missing-id",
            "status": "active",
        },
        {
            "id": "unknown-provider.json",
            "provider": "unknown",
            "label": "acct",
            "auth_index": "fp-unknown",
            "status": "active",
            "failed": 0,
            "status_message": "",
            "recent_requests": [],
        },
        {
            "id": "also-valid.json",
            "provider": "codex",
            "label": "acct2",
            "auth_index": "fp-valid-2",
            "status": "active",
            "failed": 0,
            "status_message": "",
            "recent_requests": [],
        },
    ]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_connect.return_value = mock_conn
    mock_cur.fetchall.return_value = []

    prober.sync_inventory()

    upsert_calls = [
        call
        for call in mock_cur.execute.call_args_list
        if call.args and "INSERT INTO credential_inventory" in call.args[0]
    ]
    assert len(upsert_calls) == 2
    upserted_ids = [call.args[1][0] for call in upsert_calls]
    assert upserted_ids == ["valid.json", "also-valid.json"]
    assert upsert_calls[0].args[1][1] == "anthropic"
    assert upsert_calls[1].args[1][1] == "openai"


@patch("prober.notify_policy_engine")
@patch("prober.send_slack_alert")
@patch("psycopg2.connect")
@patch("prober.get_cliproxy_auth_files")
def test_sync_inventory_skips_db_connect_when_only_invalid(mock_get_files, mock_connect, _slack, _policy):
    mock_get_files.return_value = [
        {"id": "runtime", "provider": "aistudio", "runtime_only": True, "status": "active"},
        {"id": "bad.json", "provider": "unknown", "status": "active"},
        {"provider": "anthropic", "status": "active"},
    ]

    prober.sync_inventory()

    mock_connect.assert_not_called()
