from pathlib import Path

import pytest

_PATH = Path(__file__)
CONTRACT = _PATH.parents[2] / "docs" / "UNIFIED_CONFIG_ADMIN_API_CONTRACT.md" if len(_PATH.parents) >= 3 else None

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
    if CONTRACT is None or not CONTRACT.exists():
        pytest.skip("repository docs are not mounted in the service test image")
    text = CONTRACT.read_text(encoding="utf-8")
    for required in (
        "GET /admin/config",
        "config-snapshot.v1",
        "UNIFIED_CONFIG_ADMIN_API_ENABLED=false",
        "x-management-scope: config:read",
        "64 KiB",
        "1 MiB",
        "Cache-Control: no-store",
    ):
        assert required in text


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
    if CONTRACT is None or not CONTRACT.exists():
        pytest.skip("repository docs are not mounted in the service test image")
    text = CONTRACT.read_text(encoding="utf-8")

    assert "currently implemented" in text
    assert "config_snapshot_invalid_request" in text
    assert "future read-only" not in text


def test_contract_defines_digest_presence_invariant():
    if CONTRACT is None or not CONTRACT.exists():
        pytest.skip("repository docs are not mounted in the service test image")
    text = CONTRACT.read_text(encoding="utf-8")

    assert "`digest` is present if and only if source `status` is `ok`" in text
