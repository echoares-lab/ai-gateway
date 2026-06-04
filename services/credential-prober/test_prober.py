import pytest
import json
from unittest.mock import patch, MagicMock

import prober

def test_map_status():
    # Should handle disabled -> SUSPENDED
    assert prober.map_status({"disabled": True}) == "SUSPENDED"
    
    # Should handle active -> HEALTHY
    assert prober.map_status({"disabled": False, "status": "active"}) == "HEALTHY"
    
    # Should handle error -> CRITICAL
    assert prober.map_status({"disabled": False, "status": "error"}) == "CRITICAL"
    
    # Unmapped status should default to DEGRADED
    assert prober.map_status({"disabled": False, "status": "unknown_string"}) == "DEGRADED"


@patch('urllib.request.urlopen')
def test_get_cliproxy_auth_files_success(mock_urlopen):
    # Mock successful JSON response
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "files": [{"id": "test_cred_1", "status": "active"}]
    }).encode()
    mock_resp.__enter__.return_value = mock_resp
    mock_urlopen.return_value = mock_resp

    files = prober.get_cliproxy_auth_files()
    assert len(files) == 1
    assert files[0]["id"] == "test_cred_1"

@patch('urllib.request.urlopen')
def test_get_cliproxy_auth_files_failure(mock_urlopen):
    # Mock an error from upstream
    mock_urlopen.side_effect = Exception("Connection Refused")
    files = prober.get_cliproxy_auth_files()
    assert files == []

@patch('psycopg2.connect')
@patch('prober.get_cliproxy_auth_files')
def test_sync_inventory(mock_get_files, mock_connect):
    # Mock data source
    mock_get_files.return_value = [{
        "id": "file-1.json",
        "provider": "anthropic",
        "label": "my-account@example.com",
        "auth_index": "fingerprint_abc",
        "status": "active",
        "failed": 0,
        "status_message": "",
        "recent_requests": []
    }]
    
    # Mock DB cursor
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_connect.return_value = mock_conn

    # Execute sync
    prober.sync_inventory()
    
    # Ensure insert/update was called
    assert mock_cur.execute.called
    call_args = mock_cur.execute.call_args[0]
    
    sql_query = call_args[0]
    params = call_args[1]
    
    assert "INSERT INTO credential_inventory" in sql_query
    # Check that parameters parsed out properly
    assert params[0] == "file-1.json"
    assert params[1] == "anthropic"
    assert params[2] == "my-account@example.com"
    assert params[3] == "fingerprint_abc"
    assert params[4] == "HEALTHY"
    assert params[5] == 0
    assert "recent_requests" in params[6].adapted
