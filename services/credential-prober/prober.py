import json
import logging
import os
import time
import urllib.request

import psycopg2
from notifier import send_slack_alert
from psycopg2.extras import Json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("credential-prober")

CLIPROXY_URL = os.environ.get("CLIPROXY_URL", "http://cliproxy:8317")
MGMT_KEY = os.environ.get("CLIPROXY_MANAGEMENT_KEY", "cliproxy-mgmt-H6VXKpUCzmeDuHcGmH8Oqg")
DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/postgres")
POLL_INTERVAL = int(os.environ.get("PROBER_INTERVAL_SEC", "30"))


def get_cliproxy_auth_files():
    req = urllib.request.Request(f"{CLIPROXY_URL}/v0/management/auth-files", headers={"x-management-key": MGMT_KEY})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("files", [])
    except Exception as e:
        log.error(f"Failed to fetch auth files: {e}")
        return []


def map_status(file_data):
    if file_data.get("disabled"):
        return "SUSPENDED"
    status = file_data.get("status")
    if status == "active":
        return "HEALTHY"
    if status == "error":
        return "CRITICAL"
    return "DEGRADED"


def sync_inventory():
    files = get_cliproxy_auth_files()
    if not files:
        log.warning("No auth files retrieved, skipping sync.")
        return

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Load existing statuses to detect transitions
        cur.execute("SELECT credential_id, status FROM credential_inventory")
        existing_statuses = {row[0]: row[1] for row in cur.fetchall()}

        for f in files:
            cred_id = f.get("id", "unknown")
            provider = f.get("provider", "unknown")
            label = f.get("label") or f.get("account") or f.get("email") or "unknown"
            status = map_status(f)
            fingerprint = f.get("auth_index") or "none"
            failures = f.get("failed", 0)
            status_msg = f.get("status_message") or ""
            metadata = {
                "recent_requests": f.get("recent_requests", []),
                "status_message": status_msg,
                "updated_at": f.get("updated_at", ""),
            }

            # Detect transition
            old_status = existing_statuses.get(cred_id)
            if old_status is not None and old_status != status:
                event_name = f"credential_{status.lower()}"
                reason = status_msg if status_msg else f"Status changed from {old_status} to {status}"
                send_slack_alert(event_name, cred_id, provider, reason)
            elif old_status is None and status in ("CRITICAL", "DEGRADED"):
                # Initial import is failing or degraded: send alert
                event_name = f"credential_{status.lower()}"
                reason = status_msg if status_msg else f"Initial import status: {status}"
                send_slack_alert(event_name, cred_id, provider, reason)

            cur.execute(
                """
                INSERT INTO credential_inventory
                (credential_id, provider, label, key_fingerprint, status, consecutive_failures, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (credential_id) DO UPDATE SET
                provider = EXCLUDED.provider,
                label = EXCLUDED.label,
                key_fingerprint = EXCLUDED.key_fingerprint,
                status = EXCLUDED.status,
                consecutive_failures = EXCLUDED.consecutive_failures,
                metadata = EXCLUDED.metadata;
            """,
                (cred_id, provider, label, fingerprint, status, failures, Json(metadata)),
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
