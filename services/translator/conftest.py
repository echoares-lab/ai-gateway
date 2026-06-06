"""Shared pytest fixtures for translator unit tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import fakeredis
import pytest
from core.policy.redis_store import RedisStateStore


@pytest.fixture
def fake_redis() -> fakeredis.FakeRedis:
    """In-memory Redis for rate-limit, affinity, and state-store tests."""
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def redis_state_store(fake_redis: fakeredis.FakeRedis) -> RedisStateStore:
    """RedisStateStore backed by fakeredis (rate-limit aggregator tests)."""
    return RedisStateStore(fake_redis)


@pytest.fixture
def env_patch() -> Iterator[dict[str, str]]:
    """Patch os.environ for the duration of a test; yields the patch dict."""
    patches: dict[str, str] = {}
    with patch.dict(os.environ, patches, clear=False):
        yield patches


@pytest.fixture
def policy_engine_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable policy-engine integration with fixed settings."""
    import main as t

    monkeypatch.setattr(t, "POLICY_ENGINE_ENABLED", True)
    monkeypatch.setenv("POLICY_ENGINE_ENABLED", "true")
    monkeypatch.setattr(t, "_quota_headroom_cache", None)

    # Initialize in-process evaluator if not already done
    if t._policy_evaluator is None:
        from core.policy import PolicyEvaluator

        monkeypatch.setattr(t, "_policy_evaluator", PolicyEvaluator())


@pytest.fixture
def inventory_fixtures() -> dict[str, Any]:
    """Empty in-memory inventory fixture map for InventoryStore tests."""
    return {}
