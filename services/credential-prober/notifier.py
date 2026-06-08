import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("credential-prober.notifier")

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
GATEWAY_ENGINE_URL = os.environ.get("GATEWAY_ENGINE_URL", "http://gateway-engine:4000").rstrip("/")


def send_slack_alert(
    event: str,
    credential_id: str,
    provider: str,
    reason: str,
    timestamp: str | None = None,
) -> bool:
    slack_url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not slack_url:
        log.debug("Skipping alert for %s (SLACK_WEBHOOK_URL not configured)", credential_id)
        return False

    payload = {
        "event": event,
        "credential_id": credential_id,
        "provider": provider,
        "reason": reason,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }

    try:
        req = urllib.request.Request(
            slack_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status >= 400:
                log.warning("Alert webhook returned %s", response.status)
                return False
        return True
    except Exception as e:
        log.error("Failed to send webhook alert: %s", e)
        return False


def notify_policy_engine(
    credential_id: str,
    provider: str,
    previous_status: str,
    new_status: str,
    *,
    reason: str | None = None,
    cool_down_until: datetime | None = None,
) -> bool:
    gateway-engine_url = os.environ.get("GATEWAY_ENGINE_URL", "http://gateway-engine:4000").strip().rstrip("/")
    if not gateway-engine_url:
        return False

    payload: dict[str, str] = {
        "credential_id": credential_id,
        "provider": provider,
        "previous_status": previous_status,
        "new_status": new_status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if reason:
        payload["reason"] = reason
    if cool_down_until is not None:
        payload["cool_down_until"] = cool_down_until.isoformat()

    try:
        req = urllib.request.Request(
            f"{gateway-engine_url}/v1/events/credential",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status >= 400:
                log.warning(
                    "Gateway Engine credential event returned %s for %s",
                    response.status,
                    credential_id,
                )
                return False
        return True
    except urllib.error.URLError as exc:
        log.warning("Gateway Engine credential notify failed for %s: %s", credential_id, exc)
        return False
    except Exception as exc:
        log.error("Gateway Engine credential notify error for %s: %s", credential_id, exc)
        return False
