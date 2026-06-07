import os
from utils.paths import get_project_root

def _bool(val: str | None, default: bool) -> bool:
    if val is None:
        return default
    return val.lower() not in ("0", "false", "no", "off")

class Config:
    # Network
    LITELLM_URL = os.environ.get("GATEWAY_ENGINE_LITELLM_URL") or os.environ.get("LITELLM_URL", "http://litellm:4000")
    LITELLM_ADMIN_URL = os.environ.get("GATEWAY_ENGINE_LITELLM_ADMIN_URL") or os.environ.get("LITELLM_ADMIN_URL", LITELLM_URL).rstrip("/")
    CLIPROXY_URL = os.environ.get("GATEWAY_ENGINE_CLIPROXY_URL") or os.environ.get("CLIPROXY_URL", "http://cliproxy:8317")
    CLIPROXY_WS_URL = os.environ.get("GATEWAY_ENGINE_CLIPROXY_WS_URL") or os.environ.get("CLIPROXY_WS_URL", "ws://cliproxy:8317/v1/responses")
    PORT = int(os.environ.get("GATEWAY_ENGINE_PORT", "4000"))
    
    # Timeouts and Limits
    UPSTREAM_TIMEOUT = float(os.environ.get("GATEWAY_ENGINE_UPSTREAM_TIMEOUT") or os.environ.get("UPSTREAM_TIMEOUT", "30.0"))
    HTTPX_MAX_KEEPALIVE = int(os.environ.get("GATEWAY_ENGINE_HTTPX_MAX_KEEPALIVE") or os.environ.get("HTTPX_MAX_KEEPALIVE", "20"))
    HTTPX_MAX_CONNECTIONS = int(os.environ.get("GATEWAY_ENGINE_HTTPX_MAX_CONNECTIONS") or os.environ.get("HTTPX_MAX_CONNECTIONS", "100"))
    MAX_REQUEST_BYTES = int(os.environ.get("GATEWAY_ENGINE_MAX_REQUEST_BYTES") or os.environ.get("MAX_REQUEST_BYTES", str(50 * 1024 * 1024)))

    # Redis / Cache
    REDIS_URL = os.environ.get("GATEWAY_ENGINE_REDIS_URL") or os.environ.get("REDIS_URL", "")
    CACHE_ENABLED = _bool(os.environ.get("GATEWAY_ENGINE_CACHE_ENABLED") or os.environ.get("CACHE_ENABLED"), False)
    CACHE_TTL = int(os.environ.get("GATEWAY_ENGINE_CACHE_TTL_SECONDS") or os.environ.get("CACHE_TTL_SECONDS", "60"))

    # Policy Engine
    POLICY_ENGINE_ENABLED = _bool(os.environ.get("GATEWAY_ENGINE_POLICY_ENGINE_ENABLED") or os.environ.get("POLICY_ENGINE_ENABLED"), False)
    POLICY_ENGINE_WS_EVALUATE = _bool(os.environ.get("GATEWAY_ENGINE_POLICY_ENGINE_WS_EVALUATE") or os.environ.get("POLICY_ENGINE_WS_EVALUATE"), False)
    ADMIN_POLICY_TRACE_ENABLED = _bool(os.environ.get("GATEWAY_ENGINE_ADMIN_POLICY_TRACE_ENABLED") or os.environ.get("ADMIN_POLICY_TRACE_ENABLED"), True)

    # Budget / Quota
    TEAM_BUDGET_SNAPSHOT_ENABLED = _bool(os.environ.get("GATEWAY_ENGINE_TEAM_BUDGET_SNAPSHOT_ENABLED") or os.environ.get("TEAM_BUDGET_SNAPSHOT_ENABLED"), True)
    TEAM_BUDGET_CACHE_TTL_SEC = int(os.environ.get("GATEWAY_ENGINE_TEAM_BUDGET_CACHE_TTL_SEC") or os.environ.get("TEAM_BUDGET_CACHE_TTL_SEC", "30"))
    QUOTA_HEADROOM_JSON = os.environ.get("GATEWAY_ENGINE_QUOTA_HEADROOM_JSON") or os.environ.get("QUOTA_HEADROOM_JSON", "").strip()
    TEAM_BUDGET_SNAPSHOT_JSON = os.environ.get("GATEWAY_ENGINE_TEAM_BUDGET_SNAPSHOT_JSON") or os.environ.get("TEAM_BUDGET_SNAPSHOT_JSON", "").strip()

    # Credential Sync
    CREDENTIAL_SYNC_ENABLED = _bool(os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_ENABLED"), False)
    CREDENTIAL_SYNC_INTERVAL_SEC = max(1, int(os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC", "300")))
    CREDENTIAL_SYNC_INITIAL_DELAY_SEC = max(0, int(os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC", "30")))
    CREDENTIAL_SYNC_DRY_RUN = _bool(os.environ.get("GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN"), False)

    # Auth
    LITELLM_MASTER_KEY = os.environ.get("GATEWAY_ENGINE_LITELLM_MASTER_KEY") or os.environ.get("LITELLM_MASTER_KEY", "")
    CLIPROXY_API_KEY = os.environ.get("GATEWAY_ENGINE_CLIPROXY_API_KEY") or os.environ.get("CLIPROXY_API_KEY", "")
    ADMIN_KEY = os.environ.get("GATEWAY_ENGINE_ADMIN_KEY", "")

    # Paths
    PROJECT_ROOT = get_project_root()
    GEMINI_MODEL_MAP_PATH = os.environ.get("GATEWAY_ENGINE_GEMINI_MODEL_MAP_PATH") or os.environ.get("GEMINI_MODEL_MAP_PATH", str(PROJECT_ROOT / "services/gateway-engine/gemini-model-map.json"))
    LITELLM_CONFIG_PATH = os.environ.get("GATEWAY_ENGINE_LITELLM_CONFIG_PATH") or os.environ.get("LITELLM_CONFIG_PATH", "/config/litellm-config.yaml")
    
    # Admin / Probing
    MODEL_PROBE_TIMEOUT = float(os.environ.get("GATEWAY_ENGINE_MODEL_PROBE_TIMEOUT") or os.environ.get("MODEL_PROBE_TIMEOUT", "8.0"))
    CLIPROXY_MANAGEMENT_KEY = os.environ.get("GATEWAY_ENGINE_CLIPROXY_MANAGEMENT_KEY") or os.environ.get("CLIPROXY_MANAGEMENT_KEY", "")

config = Config()
