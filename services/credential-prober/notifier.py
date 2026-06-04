import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("credential-prober.notifier")


def send_slack_alert(event: str, credential_id: str, provider: str, reason: str, timestamp: str = None) -> bool:
    """Send a structured JSON alert webhook to the configured SLACK_WEBHOOK_URL.

    If SLACK_WEBHOOK_URL is not configured, logs a warning instead of raising an error.
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        log.warning(
            "SLACK_WEBHOOK_URL is not set. Alert not sent. Event: %s, Credential: %s, Reason: %s",
            event,
            credential_id,
            reason,
        )
        return False

    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    payload = {
        "event": event,
        "credential_id": credential_id,
        "provider": provider,
        "reason": reason,
        "timestamp": timestamp,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            # urllib.request.urlopen response has .status in python 3
            status = getattr(resp, "status", 200)
            log.info(
                "Sent webhook alert to Slack. HTTP status: %d. Event: %s, Credential: %s", status, event, credential_id
            )
            return True
    except Exception as e:
        log.error("Failed to send webhook alert to Slack: %s", e)
        return False
