"""Gateway Engine configuration — single source of truth with legacy env aliases.

Effective defaults match production ``main.py`` behavior (do not flip without
an intentional migration). Alias lists are tried in order; first set wins.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SecretStoreAvailability:
    available: bool
    code: str | None = None
    missing_settings: tuple[str, ...] = ()


def _env_str(names: Sequence[str], default: str) -> str:
    for name in names:
        raw = os.environ.get(name)
        if raw is not None and raw != "":
            return raw
    return default


def _env_bool(names: Sequence[str], default: bool) -> bool:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            continue
        return raw.lower() not in ("0", "false", "no")
    return default


def _env_int(names: Sequence[str], default: int) -> int:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return default


def _env_float(names: Sequence[str], default: float) -> float:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or raw == "":
            continue
        try:
            return float(raw)
        except ValueError:
            continue
    return default


class Config:
    LITELLM_URL = _env_str(("GATEWAY_ENGINE_LITELLM_URL", "LITELLM_URL"), "http://litellm:4000")
    CLIPROXY_URL = _env_str(("GATEWAY_ENGINE_CLIPROXY_URL", "CLIPROXY_URL"), "http://cliproxy:8317")
    GATEWAY_ENGINE_PORT = _env_int(("GATEWAY_ENGINE_PORT",), 4000)
    REDIS_URL = _env_str(("GATEWAY_ENGINE_REDIS_URL", "REDIS_URL"), "")

    # Prefer LiteLLM's auth-aware Redis cache; gateway-engine cache stays off by default.
    CACHE_ENABLED = _env_bool(("CACHE_ENABLED", "GATEWAY_ENGINE_CACHE_ENABLED"), False)
    CACHE_TTL = _env_int(("CACHE_TTL_SECONDS", "GATEWAY_ENGINE_CACHE_TTL"), 60)

    UPSTREAM_TIMEOUT = _env_float(("UPSTREAM_TIMEOUT", "GATEWAY_ENGINE_UPSTREAM_TIMEOUT"), 30.0)
    LITELLM_MASTER_KEY = _env_str(("GATEWAY_ENGINE_LITELLM_MASTER_KEY", "LITELLM_MASTER_KEY"), "")
    CLIPROXY_API_KEY = _env_str(("GATEWAY_ENGINE_CLIPROXY_API_KEY", "CLIPROXY_API_KEY"), "")

    POLICY_ENGINE_ENABLED = _env_bool(("POLICY_ENGINE_ENABLED", "GATEWAY_ENGINE_POLICY_ENGINE_ENABLED"), False)
    TEAM_BUDGET_SNAPSHOT_ENABLED = _env_bool(
        ("TEAM_BUDGET_SNAPSHOT_ENABLED", "GATEWAY_ENGINE_TEAM_BUDGET_SNAPSHOT_ENABLED"),
        True,
    )
    TEAM_BUDGET_CACHE_TTL_SEC = _env_int(
        ("TEAM_BUDGET_CACHE_TTL_SEC", "GATEWAY_ENGINE_TEAM_BUDGET_CACHE_TTL_SEC"),
        30,
    )
    LITELLM_ADMIN_URL = _env_str(
        ("GATEWAY_ENGINE_LITELLM_ADMIN_URL", "LITELLM_ADMIN_URL"),
        "http://litellm:4000",
    )
    ADMIN_POLICY_TRACE_ENABLED = _env_bool(
        ("ADMIN_POLICY_TRACE_ENABLED", "GATEWAY_ENGINE_ADMIN_POLICY_TRACE_ENABLED"),
        True,
    )

    CREDENTIAL_SYNC_ENABLED = _env_bool(("GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED",), False)
    CREDENTIAL_SYNC_INTERVAL_SEC = max(
        1,
        _env_int(("GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC",), 300),
    )
    CREDENTIAL_SYNC_INITIAL_DELAY_SEC = max(
        0,
        _env_int(("GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC",), 30),
    )
    CREDENTIAL_SYNC_DRY_RUN = _env_bool(("GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN",), False)

    MODEL_RECONCILIATION_ENABLED = _env_bool(
        ("GATEWAY_ENGINE_MODEL_RECONCILIATION_ENABLED",),
        True,
    )
    MODEL_RECONCILIATION_STARTUP_DELAY_SEC = max(
        0,
        _env_int(("GATEWAY_ENGINE_MODEL_RECONCILIATION_STARTUP_DELAY_SEC",), 30),
    )
    MODEL_RECONCILIATION_INTERVAL_SEC = max(
        1,
        _env_int(("GATEWAY_ENGINE_MODEL_RECONCILIATION_INTERVAL_SEC",), 900),
    )
    MODEL_RECONCILIATION_EXPEDITED_MIN_INTERVAL_SEC = max(
        0,
        _env_int(("GATEWAY_ENGINE_MODEL_RECONCILIATION_EXPEDITED_MIN_INTERVAL_SEC",), 60),
    )
    MODEL_RECONCILIATION_TIMEOUT_SEC = max(
        1,
        _env_int(("GATEWAY_ENGINE_MODEL_RECONCILIATION_TIMEOUT_SEC",), 120),
    )

    HTTPX_MAX_KEEPALIVE = _env_int(("HTTPX_MAX_KEEPALIVE", "GATEWAY_ENGINE_HTTPX_MAX_KEEPALIVE"), 20)
    HTTPX_MAX_CONNECTIONS = _env_int(("HTTPX_MAX_CONNECTIONS", "GATEWAY_ENGINE_HTTPX_MAX_CONNECTIONS"), 100)
    MAX_REQUEST_BYTES = _env_int(
        ("MAX_REQUEST_BYTES", "GATEWAY_ENGINE_MAX_REQUEST_BYTES"),
        50 * 1024 * 1024,  # 50MB — matches prior main.py default
    )

    ENABLE_VIRTUAL_PROVIDERS = _env_bool(("GATEWAY_ENGINE_ENABLE_VIRTUAL_PROVIDERS",), False)
    QUOTA_HEADROOM_JSON = _env_str(("QUOTA_HEADROOM_JSON", "GATEWAY_ENGINE_QUOTA_HEADROOM_JSON"), "")
    TEAM_BUDGET_SNAPSHOT_JSON = _env_str(
        ("TEAM_BUDGET_SNAPSHOT_JSON", "GATEWAY_ENGINE_TEAM_BUDGET_SNAPSHOT_JSON"),
        "",
    )

    OPENBAO_ADDR = _env_str(("GATEWAY_ENGINE_OPENBAO_ADDR",), "")
    OPENBAO_AUTH_MOUNT = _env_str(("GATEWAY_ENGINE_OPENBAO_AUTH_MOUNT",), "")
    OPENBAO_ROLE = _env_str(("GATEWAY_ENGINE_OPENBAO_ROLE",), "")
    OPENBAO_KV_MOUNT = _env_str(("GATEWAY_ENGINE_OPENBAO_KV_MOUNT",), "")
    OPENBAO_KEY_PREFIX = _env_str(("GATEWAY_ENGINE_OPENBAO_KEY_PREFIX",), "")
    OPENBAO_TIMEOUT = _env_float(("GATEWAY_ENGINE_OPENBAO_TIMEOUT",), 5.0)

    @classmethod
    def secret_store_availability(cls) -> SecretStoreAvailability:
        required = {
            "GATEWAY_ENGINE_OPENBAO_ADDR": cls.OPENBAO_ADDR,
            "GATEWAY_ENGINE_OPENBAO_AUTH_MOUNT": cls.OPENBAO_AUTH_MOUNT,
            "GATEWAY_ENGINE_OPENBAO_ROLE": cls.OPENBAO_ROLE,
            "GATEWAY_ENGINE_OPENBAO_KV_MOUNT": cls.OPENBAO_KV_MOUNT,
            "GATEWAY_ENGINE_OPENBAO_KEY_PREFIX": cls.OPENBAO_KEY_PREFIX,
        }
        missing = tuple(name for name, value in required.items() if not value)
        if missing:
            return SecretStoreAvailability(
                available=False,
                code="secret_store_unavailable",
                missing_settings=missing,
            )
        return SecretStoreAvailability(available=True)


config = Config()
