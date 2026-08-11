from pathlib import Path

import yaml

# contracts/unified_config_admin.yaml is the single source of truth for these
# values and ships inside the service tree, so this file is always present —
# including in the gateway-engine unit-test image.
CONTRACT_PATH = Path(__file__).parent / "contracts" / "unified_config_admin.yaml"
CONTRACT = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))

HEALTHY_INPUT = {
    "litellm_yaml": "model_list:\n  - model_name: gpt-safe\n    litellm_params:\n      model: openai/gpt-safe\nrouter_settings:\n  routing_strategy: simple-shuffle\n",
    "registry_model_ids": ["gpt-safe"],
    "runtime_model_ids": ["gpt-safe"],
    "environment": {"OPENAI_API_KEY": "present-secret"},
}

DEGRADED_INPUT = {
    **HEALTHY_INPUT,
    "runtime_model_ids": None,
    "runtime_error": "source_timeout",
}
INVALID_CONFIG_INPUT = {**HEALTHY_INPUT, "litellm_yaml": "model_list: ["}
MISSING_ENV_INPUT = {
    **HEALTHY_INPUT,
    "litellm_yaml": "model_list:\n  - model_name: gpt-safe\n    litellm_params:\n      api_key: os.environ/OPENAI_API_KEY\n",
    "environment": {},
}
MODEL_DRIFT_INPUT = {
    **HEALTHY_INPUT,
    "registry_model_ids": ["gpt-safe", "claude-safe"],
}
PRODUCTION_SHAPED_INPUT = {
    **HEALTHY_INPUT,
    "litellm_yaml": """model_list:
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: openai/claude-sonnet-4.6
      api_key: os.environ/CLIPROXY_API_KEY
  - model_name: gemini-3-flash
    litellm_params:
      model: openai/gemini-3.flash
      api_key: os.environ/CLIPROXY_API_KEY
litellm_settings:
  fallbacks:
    - claude-sonnet-4-6: [gemini-3-flash]
  mcp_servers:
    mcp-git:
      command: uvx
      args: [mcp-server-git, --repository, /private/repository]
""",
    "registry_model_ids": ["claude-sonnet-4-6", "gemini-3-flash"],
    "runtime_model_ids": ["claude-sonnet-4-6", "gemini-3-flash"],
    "environment": {"CLIPROXY_API_KEY": "fixture-secret"},
}
SECRET_LOOKING_INPUT = {
    **HEALTHY_INPUT,
    "litellm_yaml": "model_list:\n  - model_name: gpt-safe\n    litellm_params:\n      api_key: sk-do-not-return\n      api_base: https://secret.example/v1\n",
}


def test_contract_defines_exact_boundary():
    assert CONTRACT["method"] == "GET"
    assert CONTRACT["route"] == "/admin/config"
    assert CONTRACT["schema"] == "config-snapshot.v1"
    assert CONTRACT["flag"] == "UNIFIED_CONFIG_ADMIN_API_ENABLED"
    assert CONTRACT["flag_default"] is False
    assert CONTRACT["management_scope"] == "config:read"
    assert CONTRACT["cache_control"] == "no-store"
    assert CONTRACT["limits"]["serialized_response_bytes"] == 64 * 1024
    assert CONTRACT["limits"]["deployed_config_input_bytes"] == 1024 * 1024


def test_contract_fixture_names_are_stable():
    assert HEALTHY_INPUT["runtime_model_ids"] == ["gpt-safe"]
    assert DEGRADED_INPUT["runtime_error"] == "source_timeout"
    assert INVALID_CONFIG_INPUT["litellm_yaml"].endswith("[")
    assert MISSING_ENV_INPUT["environment"] == {}
    assert MODEL_DRIFT_INPUT["registry_model_ids"][-1] == "claude-safe"
    assert "litellm_settings" in PRODUCTION_SHAPED_INPUT["litellm_yaml"]
    assert "openai/claude" in PRODUCTION_SHAPED_INPUT["litellm_yaml"]
    assert "sk-do-not-return" in SECRET_LOOKING_INPUT["litellm_yaml"]


def test_contract_describes_the_current_route_and_invalid_request_error():
    assert CONTRACT["implementation_state"] == "implemented"
    assert CONTRACT["http_errors"]["invalid_request"] == {
        "status": 400,
        "code": "config_snapshot_invalid_request",
    }


def test_contract_defines_digest_presence_invariant():
    # `digest` is present if and only if source `status` is `ok`; it is omitted
    # for missing, invalid, and unavailable sources.
    assert CONTRACT["digest_present_when_source_status"] == "ok"
    assert "digest" not in CONTRACT["source_errors"]
