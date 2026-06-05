"""Unit tests for CLIProxy pool priority sync (issue 38-13)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from pool_sync import (
    PoolMemberPriority,
    PoolSyncConfig,
    effective_priority,
    fetch_pool_members,
    load_priority_backup,
    resolve_member_priorities,
    rollback_pool_priorities,
    sync_pool_priorities,
    write_priority_backup,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _fake_opener(responses: list[dict]):
    calls: list[tuple[str, str, dict | None]] = []

    def opener(req, timeout=15):  # noqa: ARG001
        method = req.method
        url = req.full_url
        body = None
        if req.data:
            body = json.loads(req.data.decode())
        calls.append((method, url, body))
        return _FakeResponse(responses.pop(0))

    opener.calls = calls  # type: ignore[attr-defined]
    return opener


def test_effective_priority_uses_member_value():
    assert effective_priority("native", 42) == 42


def test_effective_priority_falls_back_to_tier_default():
    assert effective_priority("native", 0) == 100
    assert effective_priority("antigravity", 0) == 50
    assert effective_priority("emergency", 0) == 10


def test_resolve_member_priorities_picks_highest_per_credential():
    members = [
        PoolMemberPriority("a.json", "pool-1", "antigravity", 0, "fill-first"),
        PoolMemberPriority("a.json", "pool-2", "native", 0, "fill-first"),
        PoolMemberPriority("b.json", "pool-1", "emergency", 5, "fill-first"),
    ]
    resolved = resolve_member_priorities(members)
    assert resolved == {"a.json": 100, "b.json": 5}


def test_fetch_pool_members_from_fixtures():
    fixtures = [
        PoolMemberPriority("claude-a.json", "anthropic-primary", "native", 100, "fill-first"),
    ]
    rows = fetch_pool_members(None, fixtures=fixtures)
    assert len(rows) == 1
    assert rows[0].credential_id == "claude-a.json"


def test_fetch_pool_members_from_postgres():
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("claude-a.json", "anthropic-primary", "native", 80, "fill-first"),
    ]
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    def connect():
        return conn

    rows = fetch_pool_members(connect)
    assert len(rows) == 1
    assert rows[0].effective_priority == 80


def test_sync_skipped_when_feature_flag_off(tmp_path: Path):
    config = PoolSyncConfig(
        enabled=False,
        cliproxy_url="http://cliproxy:8317",
        management_key="test-key",
        backup_dir=tmp_path,
        database_url="",
        members_fixture=[
            PoolMemberPriority("claude-a.json", "pool-1", "native", 100, "fill-first"),
        ],
    )
    result = sync_pool_priorities(config)
    assert result.enabled is False
    assert result.patched == []


def test_sync_patches_changed_priorities(tmp_path: Path):
    opener = _fake_opener(
        [
            {
                "files": [
                    {"id": "claude-a.json", "priority": 0},
                    {"id": "claude-b.json", "priority": 50},
                ]
            },
            {"status": "ok"},
        ]
    )
    config = PoolSyncConfig(
        enabled=True,
        cliproxy_url="http://mock:8317",
        management_key="test-key",
        backup_dir=tmp_path,
        database_url="",
        members_fixture=[
            PoolMemberPriority("claude-a.json", "pool-1", "native", 100, "fill-first"),
            PoolMemberPriority("claude-b.json", "pool-1", "native", 50, "fill-first"),
        ],
    )
    result = sync_pool_priorities(config, opener=opener)
    assert result.ok
    assert result.patched == ["claude-a.json"]
    assert result.unchanged == ["claude-b.json"]
    assert result.backup_path is not None
    assert len(opener.calls) == 2  # type: ignore[attr-defined]
    assert opener.calls[1][0] == "PATCH"  # type: ignore[attr-defined]
    assert opener.calls[1][2] == {"name": "claude-a.json", "priority": 100}  # type: ignore[attr-defined]


def test_sync_dry_run_does_not_write_backup(tmp_path: Path):
    opener = _fake_opener([{"files": [{"id": "claude-a.json", "priority": 0}]}])
    config = PoolSyncConfig(
        enabled=True,
        cliproxy_url="http://mock:8317",
        management_key="test-key",
        backup_dir=tmp_path,
        database_url="",
        members_fixture=[
            PoolMemberPriority("claude-a.json", "pool-1", "native", 100, "fill-first"),
        ],
    )
    result = sync_pool_priorities(config, dry_run=True, opener=opener)
    assert result.patched == ["claude-a.json"]
    assert result.backup_path is None
    assert list(tmp_path.iterdir()) == []


def test_backup_and_rollback_round_trip(tmp_path: Path):
    snapshot = {"claude-a.json": 100, "claude-b.json": None}
    backup_path = write_priority_backup(tmp_path, snapshot)
    loaded = load_priority_backup(backup_path)
    assert loaded == snapshot

    opener = _fake_opener([{"status": "ok"}, {"status": "ok"}])
    config = PoolSyncConfig(
        enabled=True,
        cliproxy_url="http://mock:8317",
        management_key="test-key",
        backup_dir=tmp_path,
        database_url="",
    )
    result = rollback_pool_priorities(config, backup_file=backup_path, opener=opener)
    assert result.ok
    assert result.patched == ["claude-a.json"]
    assert len(opener.calls) == 1  # type: ignore[attr-defined]
