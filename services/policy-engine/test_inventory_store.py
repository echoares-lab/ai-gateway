"""Unit tests for credential_inventory routing exclusion (P0-6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from inventory_store import InventoryStore, _status_excludes_routing


def test_status_excludes_critical_and_suspended():
    now = datetime.now(timezone.utc)
    assert _status_excludes_routing("CRITICAL", None, now) is True
    assert _status_excludes_routing("SUSPENDED", None, now) is True


def test_degraded_excluded_with_active_or_missing_cooldown():
    now = datetime.now(timezone.utc)
    future = now + timedelta(minutes=5)
    past = now - timedelta(minutes=1)
    assert _status_excludes_routing("DEGRADED", future, now) is True
    assert _status_excludes_routing("DEGRADED", None, now) is True
    assert _status_excludes_routing("DEGRADED", past, now) is False


def test_routing_snapshots_critical_status():
    inventory = InventoryStore(None, enabled=False, fixtures={"cred-bad": ("anthropic", None, "CRITICAL")})
    snaps = inventory.routing_snapshots(["cred-bad"])
    assert len(snaps) == 1
    assert snaps[0].pre_emptive_degraded is True


def test_routing_snapshots_healthy_not_returned():
    inventory = InventoryStore(None, enabled=False, fixtures={"cred-ok": ("openai", None, "HEALTHY")})
    assert inventory.routing_snapshots(["cred-ok"]) == []
