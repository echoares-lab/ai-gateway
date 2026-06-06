import json
import logging
import os
import time
import urllib.request
from datetime import datetime, timezone

import psycopg2
from credential_probe import (
    ROUTING_EXCLUDED,
    build_inventory_payload,
    build_transition_payload,
    compute_cool_down_until,
    map_auth_file_status,
    normalize_provider,
    should_emit_transition,
)
from notifier import notify_policy_engine, send_slack_alert
from psycopg2.extras import Json

__all__ = ["compute_cool_down_until", "map_status", "normalize_provider", "sync_inventory"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("credential-prober")

CLIPROXY_URL = os.environ.get("CLIPROXY_URL", "http://cliproxy:8317")
MGMT_KEY = os.environ.get("CLIPROXY_MANAGEMENT_KEY", "")
DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/postgres")
POLL_INTERVAL = int(os.environ.get("PROBER_INTERVAL_SEC", "30"))
DEGRADED_COOLDOWN_SEC = int(os.environ.get("PROBER_DEGRADED_COOLDOWN_SEC", "60"))
CRITICAL_COOLDOWN_SEC = int(os.environ.get("PROBER_CRITICAL_COOLDOWN_SEC", "604800"))


def map_status(file_data):
    return map_auth_file_status(file_data)


def get_cliproxy_auth_files():
    req = urllib.request.Request(f"{CLIPROXY_URL}/v0/management/auth-files", headers={"x-management-key": MGMT_KEY})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("files", [])
    except Exception as e:
        log.error(f"Failed to fetch auth files: {e}")
        return []


def _emit_transition(
    cred_id: str,
    provider: str,
    old_status: str | None,
    new_status: str,
    reason: str,
    cool_down_until: datetime | None,
) -> None:
    previous = old_status or "UNKNOWN"
    send_slack_alert(f"credential_{new_status.lower()}", cred_id, provider, reason)
    notify_policy_engine(
        cred_id,
        provider,
        previous,
        new_status,
        reason=reason,
        cool_down_until=cool_down_until if new_status in ROUTING_EXCLUDED else None,
    )


def sync_inventory():
    files = get_cliproxy_auth_files()
    if not files:
        log.warning("No auth files retrieved, skipping sync.")
        return

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT credential_id, status FROM credential_inventory")
        existing_statuses = {row[0]: row[1] for row in cur.fetchall()}
        now = datetime.now(timezone.utc)

        for f in files:
            payload = build_inventory_payload(
                f,
                now=now,
                degraded_cooldown_sec=DEGRADED_COOLDOWN_SEC,
                critical_cooldown_sec=CRITICAL_COOLDOWN_SEC,
            )
            cred_id = payload["credential_id"]
            provider = payload["provider"]
            status = payload["status"]
            cool_down_until = payload["cool_down_until"]

            old_status = existing_statuses.get(cred_id)
            if should_emit_transition(old_status, status):
                transition = build_transition_payload(
                    credential_id=cred_id,
                    provider=provider,
                    old_status=old_status,
                    new_status=status,
                    status_message=payload["metadata"]["status_message"],
                    cool_down_until=cool_down_until,
                )
                _emit_transition(
                    transition["credential_id"],
                    transition["provider"],
                    old_status,
                    transition["new_status"],
                    transition["reason"],
                    transition["cool_down_until"],
                )

            cur.execute(
                """
                INSERT INTO credential_inventory
                (credential_id, provider, label, key_fingerprint, status,
                 cool_down_until, consecutive_failures, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (credential_id) DO UPDATE SET
                provider = EXCLUDED.provider,
                label = EXCLUDED.label,
                key_fingerprint = EXCLUDED.key_fingerprint,
                status = EXCLUDED.status,
                cool_down_until = EXCLUDED.cool_down_until,
                consecutive_failures = EXCLUDED.consecutive_failures,
                metadata = EXCLUDED.metadata;
            """,
                (
                    payload["credential_id"],
                    payload["provider"],
                    payload["label"],
                    payload["key_fingerprint"],
                    payload["status"],
                    payload["cool_down_until"],
                    payload["consecutive_failures"],
                    Json(payload["metadata"]),
                ),
            )

        conn.commit()
        cur.close()
        conn.close()
        log.info(f"Successfully synced {len(files)} credentials to inventory.")
    except Exception as e:
        log.error(f"Database sync failed: {e}")


if __name__ == "__main__":
    log.info(f"Starting credential prober. Polling every {POLL_INTERVAL} seconds.")
    while True:
        sync_inventory()
        time.sleep(POLL_INTERVAL)
