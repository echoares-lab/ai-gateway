import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("credential-prober.notifier")

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")


def send_slack_alert(event: str, credential_id: str, provider: str, reason: str):
    if not SLACK_WEBHOOK_URL:
        log.debug("Skipping alert for %s (SLACK_WEBHOOK_URL not configured)", credential_id)
        return

    payload = {
        "event": event,
        "credential_id": credential_id,
        "provider": provider,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status >= 400:
                log.warning("Alert webhook returned %s", response.status)
    except Exception as e:
        log.error("Failed to send webhook alert: %s", e)
