"""CLIProxy credential priority sync from Postgres pool members (Epic #38, issue 38-13).

Optional, feature-flagged sync pushes ``credential_pool_members`` tier + priority
to CLIProxy auth files via the management API. Pools with ``affinity_mode =
quota-aware`` are skipped so fill-first ordering is not overridden.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

TIER_DEFAULT_PRIORITY: dict[str, int] = {
    "native": 100,
    "antigravity": 50,
    "emergency": 10,
}

POOL_MEMBER_SELECT = """
    SELECT m.credential_id, m.pool_id, m.tier, m.priority, p.affinity_mode
    FROM credential_pool_members m
    JOIN credential_pools p ON p.pool_id = m.pool_id
    WHERE m.enabled = true
      AND p.enabled = true
      AND p.affinity_mode <> 'quota-aware'
    ORDER BY m.pool_id, m.tier, m.priority DESC, m.credential_id
"""


class DbConnection(Protocol):
    def cursor(self) -> Any: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class PoolMemberPriority:
    credential_id: str
    pool_id: str
    tier: str
    member_priority: int
    affinity_mode: str

    @property
    def effective_priority(self) -> int:
        if self.member_priority != 0:
            return self.member_priority
        return TIER_DEFAULT_PRIORITY.get(self.tier, 0)


@dataclass
class SyncResult:
    enabled: bool
    skipped_quota_aware_pools: int = 0
    members_considered: int = 0
    patched: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    backup_path: str | None = None
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.enabled and not self.errors


def effective_priority(tier: str, member_priority: int) -> int:
    if member_priority != 0:
        return member_priority
    return TIER_DEFAULT_PRIORITY.get(tier, 0)


def resolve_member_priorities(members: list[PoolMemberPriority]) -> dict[str, int]:
    """Collapse pool members to one CLIProxy auth file → highest effective priority."""
    resolved: dict[str, int] = {}
    for member in members:
        target = member.effective_priority
        current = resolved.get(member.credential_id)
        if current is None or target > current:
            resolved[member.credential_id] = target
    return resolved


@dataclass
class PoolSyncConfig:
    enabled: bool
    cliproxy_url: str
    management_key: str
    backup_dir: Path
    database_url: str
    connect: Callable[[], DbConnection] | None = None
    members_fixture: list[PoolMemberPriority] | None = None

    @classmethod
    def from_env(cls) -> PoolSyncConfig:
        enabled = os.environ.get("CLIPROXY_PRIORITY_SYNC_ENABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        cliproxy_url = os.environ.get("CLIPROXY_URL", "http://cliproxy:8317").rstrip("/")
        management_key = os.environ.get("CLIPROXY_MANAGEMENT_KEY", "").strip()
        backup_dir = Path(
            os.environ.get(
                "CLIPROXY_PRIORITY_BACKUP_DIR",
                os.path.expanduser("~/.cliproxy/priority-backups"),
            )
        )
        database_url = os.environ.get("DATABASE_URL", "").strip()

        connect: Callable[[], DbConnection] | None = None
        if database_url:
            try:
                import psycopg2  # type: ignore[import-untyped]

                def _connect() -> DbConnection:
                    return psycopg2.connect(database_url)

                probe = _connect()
                probe.close()
                connect = _connect
            except Exception as exc:  # noqa: BLE001
                logger.warning("Postgres unavailable for pool sync: %s", exc)

        return cls(
            enabled=enabled,
            cliproxy_url=cliproxy_url,
            management_key=management_key,
            backup_dir=backup_dir,
            database_url=database_url,
            connect=connect,
        )


def fetch_pool_members(
    connect: Callable[[], DbConnection] | None,
    *,
    fixtures: list[PoolMemberPriority] | None = None,
) -> list[PoolMemberPriority]:
    if fixtures is not None:
        return list(fixtures)
    if connect is None:
        return []
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(POOL_MEMBER_SELECT)
            rows = cur.fetchall()
    finally:
        conn.close()

    members: list[PoolMemberPriority] = []
    for credential_id, pool_id, tier, priority, affinity_mode in rows:
        members.append(
            PoolMemberPriority(
                credential_id=str(credential_id),
                pool_id=str(pool_id),
                tier=str(tier),
                member_priority=int(priority or 0),
                affinity_mode=str(affinity_mode),
            )
        )
    return members


def _management_request(
    *,
    method: str,
    url: str,
    management_key: str,
    body: dict[str, Any] | None = None,
    opener: Callable[..., Any] | None = None,
) -> Any:
    headers = {"x-management-key": management_key}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=15) as resp:
        raw = resp.read().decode()
        if not raw.strip():
            return {}
        return json.loads(raw)


def fetch_cliproxy_priorities(
    cliproxy_url: str,
    management_key: str,
    *,
    opener: Callable[..., Any] | None = None,
) -> dict[str, int | None]:
    if not management_key:
        raise ValueError("CLIPROXY_MANAGEMENT_KEY is required for CLIProxy sync")
    payload = _management_request(
        method="GET",
        url=f"{cliproxy_url}/v0/management/auth-files",
        management_key=management_key,
        opener=opener,
    )
    priorities: dict[str, int | None] = {}
    for entry in payload.get("files", []):
        if not isinstance(entry, dict):
            continue
        file_id = entry.get("id") or entry.get("name")
        if not file_id:
            continue
        raw_priority = entry.get("priority")
        if raw_priority is None:
            priorities[str(file_id)] = None
        else:
            priorities[str(file_id)] = int(raw_priority)
    return priorities


def patch_cliproxy_priority(
    cliproxy_url: str,
    management_key: str,
    auth_file: str,
    priority: int,
    *,
    opener: Callable[..., Any] | None = None,
) -> None:
    _management_request(
        method="PATCH",
        url=f"{cliproxy_url}/v0/management/auth-files/fields",
        management_key=management_key,
        body={"name": auth_file, "priority": priority},
        opener=opener,
    )


def write_priority_backup(
    backup_dir: Path,
    priorities: dict[str, int | None],
    *,
    timestamp: datetime | None = None,
) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp or datetime.now(timezone.utc)
    stamp = ts.strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"pool-sync-{stamp}.json"
    payload = {
        "version": 1,
        "captured_at": ts.isoformat(),
        "files": priorities,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    latest = backup_dir / "pool-sync-latest.json"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def load_priority_backup(path: Path) -> dict[str, int | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = payload.get("files", {})
    if not isinstance(files, dict):
        raise ValueError(f"invalid backup format in {path}")
    return {str(name): (int(value) if value is not None else None) for name, value in files.items()}


def sync_pool_priorities(
    config: PoolSyncConfig,
    *,
    dry_run: bool = False,
    opener: Callable[..., Any] | None = None,
) -> SyncResult:
    result = SyncResult(enabled=config.enabled, dry_run=dry_run)
    if not config.enabled:
        logger.info("CLIProxy priority sync disabled (CLIPROXY_PRIORITY_SYNC_ENABLED)")
        return result

    members = fetch_pool_members(config.connect, fixtures=config.members_fixture)
    result.members_considered = len(members)
    if not members:
        logger.warning("No eligible pool members found for priority sync")
        return result

    targets = resolve_member_priorities(members)
    try:
        current = fetch_cliproxy_priorities(
            config.cliproxy_url,
            config.management_key,
            opener=opener,
        )
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"fetch auth-files failed: {exc}")
        return result

    if not dry_run:
        try:
            backup_path = write_priority_backup(config.backup_dir, current)
            result.backup_path = str(backup_path)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"backup failed: {exc}")
            return result

    for auth_file, target_priority in sorted(targets.items()):
        existing = current.get(auth_file)
        if existing == target_priority:
            result.unchanged.append(auth_file)
            continue
        if dry_run:
            result.patched.append(auth_file)
            continue
        try:
            patch_cliproxy_priority(
                config.cliproxy_url,
                config.management_key,
                auth_file,
                target_priority,
                opener=opener,
            )
            result.patched.append(auth_file)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"patch {auth_file}: {exc}")

    return result


def rollback_pool_priorities(
    config: PoolSyncConfig,
    *,
    backup_file: Path | None = None,
    dry_run: bool = False,
    opener: Callable[..., Any] | None = None,
) -> SyncResult:
    result = SyncResult(enabled=config.enabled, dry_run=dry_run)
    if not config.enabled:
        logger.info("CLIProxy priority sync disabled (CLIPROXY_PRIORITY_SYNC_ENABLED)")
        return result
    if not config.management_key:
        result.errors.append("CLIPROXY_MANAGEMENT_KEY is required for rollback")
        return result

    path = backup_file or (config.backup_dir / "pool-sync-latest.json")
    if not path.exists():
        result.errors.append(f"backup not found: {path}")
        return result

    try:
        snapshot = load_priority_backup(path)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"load backup failed: {exc}")
        return result

    for auth_file, priority in sorted(snapshot.items()):
        if priority is None:
            continue
        if dry_run:
            result.patched.append(auth_file)
            continue
        try:
            patch_cliproxy_priority(
                config.cliproxy_url,
                config.management_key,
                auth_file,
                priority,
                opener=opener,
            )
            result.patched.append(auth_file)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"rollback {auth_file}: {exc}")

    result.backup_path = str(path)
    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync CLIProxy credential priorities from pool members")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("sync", "rollback"),
        default="sync",
        help="sync (default) pushes pool priorities; rollback restores latest backup",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute changes without PATCH or backup write")
    parser.add_argument("--backup", type=Path, help="Backup file for rollback (default: pool-sync-latest.json)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = PoolSyncConfig.from_env()

    if args.command == "rollback":
        result = rollback_pool_priorities(
            config,
            backup_file=args.backup,
            dry_run=args.dry_run,
        )
    else:
        result = sync_pool_priorities(config, dry_run=args.dry_run)

    logger.info(
        "pool sync %s: enabled=%s patched=%d unchanged=%d errors=%d backup=%s",
        args.command,
        result.enabled,
        len(result.patched),
        len(result.unchanged),
        len(result.errors),
        result.backup_path,
    )
    for err in result.errors:
        logger.error("%s", err)
    if not result.enabled:
        return 0
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
