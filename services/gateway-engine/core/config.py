import os


class Config:
    LITELLM_URL = os.environ.get("GATEWAY_ENGINE_LITELLM_URL") or os.environ.get("LITELLM_URL", "http://litellm:4000")
    CLIPROXY_URL = os.environ.get("GATEWAY_ENGINE_CLIPROXY_URL") or os.environ.get(
        "CLIPROXY_URL", "http://cliproxy:8317"
    )
    GATEWAY_ENGINE_PORT = int(os.environ.get("GATEWAY_ENGINE_PORT", "4000"))
    REDIS_URL = os.environ.get("GATEWAY_ENGINE_REDIS_URL") or os.environ.get("REDIS_URL", "")
    CACHE_ENABLED = os.environ.get("GATEWAY_ENGINE_CACHE_ENABLED", "false").lower() == "true"
    CACHE_TTL = int(os.environ.get("GATEWAY_ENGINE_CACHE_TTL", "60"))
    UPSTREAM_TIMEOUT = float(os.environ.get("GATEWAY_ENGINE_UPSTREAM_TIMEOUT", "30.0"))
    LITELLM_MASTER_KEY = os.environ.get("GATEWAY_ENGINE_LITELLM_MASTER_KEY") or os.environ.get("LITELLM_MASTER_KEY", "")
    CLIPROXY_API_KEY = os.environ.get("GATEWAY_ENGINE_CLIPROXY_API_KEY") or os.environ.get("CLIPROXY_API_KEY", "")
    POLICY_ENGINE_ENABLED = os.environ.get("GATEWAY_ENGINE_POLICY_ENGINE_ENABLED", "false").lower() == "true"
    TEAM_BUDGET_SNAPSHOT_ENABLED = (
        os.environ.get("GATEWAY_ENGINE_TEAM_BUDGET_SNAPSHOT_ENABLED", "true").lower() == "true"
    )
    TEAM_BUDGET_CACHE_TTL_SEC = int(os.environ.get("GATEWAY_ENGINE_TEAM_BUDGET_CACHE_TTL_SEC", "60"))
    LITELLM_ADMIN_URL = os.environ.get("GATEWAY_ENGINE_LITELLM_ADMIN_URL") or os.environ.get(
        "LITELLM_ADMIN_URL", "http://litellm:4000"
    )
    ADMIN_POLICY_TRACE_ENABLED = os.environ.get("GATEWAY_ENGINE_ADMIN_POLICY_TRACE_ENABLED", "true").lower() == "true"
    CREDENTIAL_SYNC_ENABLED = os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED", "true").lower() == "true"
    CREDENTIAL_SYNC_INTERVAL_SEC = int(os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC", "300"))
    CREDENTIAL_SYNC_INITIAL_DELAY_SEC = int(os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC", "10"))
    CREDENTIAL_SYNC_DRY_RUN = os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN", "false").lower() == "true"
    HTTPX_MAX_KEEPALIVE = int(os.environ.get("GATEWAY_ENGINE_HTTPX_MAX_KEEPALIVE", "20"))
    HTTPX_MAX_CONNECTIONS = int(os.environ.get("GATEWAY_ENGINE_HTTPX_MAX_CONNECTIONS", "100"))
    MAX_REQUEST_BYTES = int(os.environ.get("GATEWAY_ENGINE_MAX_REQUEST_BYTES", "10485760"))  # 10MB
    ENABLE_VIRTUAL_PROVIDERS = os.environ.get("GATEWAY_ENGINE_ENABLE_VIRTUAL_PROVIDERS", "false").lower() == "true"
    QUOTA_HEADROOM_JSON = os.environ.get("GATEWAY_ENGINE_QUOTA_HEADROOM_JSON", "")
    TEAM_BUDGET_SNAPSHOT_JSON = os.environ.get("GATEWAY_ENGINE_TEAM_BUDGET_SNAPSHOT_JSON", "")


config = Config()
