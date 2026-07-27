"""Lock Config default matrix (production-compatible defaults with cleared env)."""

from __future__ import annotations

import importlib

import pytest

# Env vars that Config (or aliases) may read — cleared so defaults apply.
_CONFIG_ENV_KEYS = (
    "GATEWAY_ENGINE_LITELLM_URL",
    "LITELLM_URL",
    "GATEWAY_ENGINE_CLIPROXY_URL",
    "CLIPROXY_URL",
    "GATEWAY_ENGINE_PORT",
    "GATEWAY_ENGINE_REDIS_URL",
    "REDIS_URL",
    "CACHE_ENABLED",
    "GATEWAY_ENGINE_CACHE_ENABLED",
    "CACHE_TTL_SECONDS",
    "GATEWAY_ENGINE_CACHE_TTL",
    "UPSTREAM_TIMEOUT",
    "GATEWAY_ENGINE_UPSTREAM_TIMEOUT",
    "GATEWAY_ENGINE_LITELLM_MASTER_KEY",
    "LITELLM_MASTER_KEY",
    "GATEWAY_ENGINE_CLIPROXY_API_KEY",
    "CLIPROXY_API_KEY",
    "POLICY_ENGINE_ENABLED",
    "GATEWAY_ENGINE_POLICY_ENGINE_ENABLED",
    "TEAM_BUDGET_SNAPSHOT_ENABLED",
    "GATEWAY_ENGINE_TEAM_BUDGET_SNAPSHOT_ENABLED",
    "TEAM_BUDGET_CACHE_TTL_SEC",
    "GATEWAY_ENGINE_TEAM_BUDGET_CACHE_TTL_SEC",
    "GATEWAY_ENGINE_LITELLM_ADMIN_URL",
    "LITELLM_ADMIN_URL",
    "ADMIN_POLICY_TRACE_ENABLED",
    "GATEWAY_ENGINE_ADMIN_POLICY_TRACE_ENABLED",
    "GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED",
    "GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC",
    "GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC",
    "GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN",
    "GATEWAY_ENGINE_MODEL_RECONCILIATION_ENABLED",
    "GATEWAY_ENGINE_MODEL_RECONCILIATION_STARTUP_DELAY_SEC",
    "GATEWAY_ENGINE_MODEL_RECONCILIATION_INTERVAL_SEC",
    "GATEWAY_ENGINE_MODEL_RECONCILIATION_EXPEDITED_MIN_INTERVAL_SEC",
    "GATEWAY_ENGINE_MODEL_RECONCILIATION_TIMEOUT_SEC",
    "GATEWAY_ENGINE_MODEL_RECONCILIATION_PROBE_STALE_SEC",
    "HTTPX_MAX_KEEPALIVE",
    "GATEWAY_ENGINE_HTTPX_MAX_KEEPALIVE",
    "HTTPX_MAX_CONNECTIONS",
    "GATEWAY_ENGINE_HTTPX_MAX_CONNECTIONS",
    "MAX_REQUEST_BYTES",
    "GATEWAY_ENGINE_MAX_REQUEST_BYTES",
    "GATEWAY_ENGINE_ENABLE_VIRTUAL_PROVIDERS",
    "QUOTA_HEADROOM_JSON",
    "GATEWAY_ENGINE_QUOTA_HEADROOM_JSON",
    "TEAM_BUDGET_SNAPSHOT_JSON",
    "GATEWAY_ENGINE_TEAM_BUDGET_SNAPSHOT_JSON",
)


@pytest.fixture
def fresh_config(monkeypatch):
    for key in _CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    import core.config as config_mod

    return importlib.reload(config_mod)


def test_config_default_matrix(fresh_config):
    c = fresh_config.Config
    assert c.CACHE_ENABLED is False
    assert c.CACHE_TTL == 60
    assert c.MAX_REQUEST_BYTES == 50 * 1024 * 1024
    assert c.CREDENTIAL_SYNC_ENABLED is False
    assert c.TEAM_BUDGET_CACHE_TTL_SEC == 30
    assert c.TEAM_BUDGET_SNAPSHOT_ENABLED is True
    assert c.POLICY_ENGINE_ENABLED is False
    assert c.HTTPX_MAX_KEEPALIVE == 20
    assert c.HTTPX_MAX_CONNECTIONS == 100
    assert c.UPSTREAM_TIMEOUT == 30.0
    assert c.ADMIN_POLICY_TRACE_ENABLED is True
    assert c.CREDENTIAL_SYNC_INTERVAL_SEC == 300
    assert c.CREDENTIAL_SYNC_INITIAL_DELAY_SEC == 30
    assert c.CREDENTIAL_SYNC_DRY_RUN is False
    assert c.MODEL_RECONCILIATION_ENABLED is True
    assert c.MODEL_RECONCILIATION_STARTUP_DELAY_SEC == 30
    assert c.MODEL_RECONCILIATION_INTERVAL_SEC == 900
    assert c.MODEL_RECONCILIATION_EXPEDITED_MIN_INTERVAL_SEC == 60
    assert c.MODEL_RECONCILIATION_TIMEOUT_SEC == 120
    assert c.MODEL_RECONCILIATION_PROBE_STALE_SEC == 300


def test_cache_enabled_legacy_alias(monkeypatch):
    for key in _CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CACHE_ENABLED", "true")
    import core.config as config_mod

    mod = importlib.reload(config_mod)
    assert mod.Config.CACHE_ENABLED is True


def test_cache_ttl_legacy_alias(monkeypatch):
    for key in _CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CACHE_TTL_SECONDS", "120")
    import core.config as config_mod

    mod = importlib.reload(config_mod)
    assert mod.Config.CACHE_TTL == 120


def test_gateway_engine_alias_preferred_when_first(monkeypatch):
    """Alias lists are tried in order — first set wins."""
    for key in _CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CACHE_ENABLED", "false")
    monkeypatch.setenv("GATEWAY_ENGINE_CACHE_ENABLED", "true")
    import core.config as config_mod

    mod = importlib.reload(config_mod)
    # CACHE_ENABLED is listed first, so legacy false wins over GATEWAY_ENGINE_* true
    assert mod.Config.CACHE_ENABLED is False
