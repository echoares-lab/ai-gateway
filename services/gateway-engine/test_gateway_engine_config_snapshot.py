import json
from datetime import datetime, timezone

from api.config_snapshot import MAX_DEPTH, MAX_ENTRIES, MAX_STRING, SnapshotInputs, build_config_snapshot
from test_gateway_engine_unified_config_contract import (
    DEGRADED_INPUT,
    HEALTHY_INPUT,
    INVALID_CONFIG_INPUT,
    MISSING_ENV_INPUT,
    SECRET_LOOKING_INPUT,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def _inputs(fixture, **overrides):
    return SnapshotInputs(
        litellm_yaml=fixture.get("litellm_yaml"),
        litellm_status=overrides.pop("litellm_status", "ok"),
        registry_model_ids=tuple(fixture["registry_model_ids"])
        if fixture.get("registry_model_ids") is not None
        else None,
        registry_status=overrides.pop("registry_status", "ok"),
        runtime_model_ids=tuple(fixture["runtime_model_ids"]) if fixture.get("runtime_model_ids") is not None else None,
        runtime_status=overrides.pop("runtime_status", "unavailable" if fixture.get("runtime_error") else "ok"),
        environment=fixture["environment"],
        generated_at=overrides.pop("generated_at", NOW),
        source_errors=overrides.pop(
            "source_errors",
            (("runtime-visible-models", fixture["runtime_error"]),) if fixture.get("runtime_error") else (),
        ),
        **overrides,
    )


def test_healthy_snapshot_is_deterministic():
    snapshot = build_config_snapshot(_inputs(HEALTHY_INPUT))

    assert snapshot["schema"] == "config-snapshot.v1"
    assert snapshot["status"] == "ok"
    assert snapshot["models"]["configured"] == ["gpt-safe"]
    assert snapshot["drift"]["status"] == "clean"
    assert snapshot["routing"] == {"routing_strategy": "simple-shuffle"}


def test_secret_input_never_leaks_values_urls_or_paths():
    serialized = json.dumps(build_config_snapshot(_inputs(SECRET_LOOKING_INPUT)))

    for forbidden in ("sk-do-not-return", "secret.example", "https://", "/home/", "/root/"):
        assert forbidden not in serialized


def test_missing_runtime_source_is_unknown_not_false_drift():
    snapshot = build_config_snapshot(_inputs(DEGRADED_INPUT))

    assert snapshot["status"] == "degraded"
    assert snapshot["drift"]["status"] == "unknown"
    assert {error["code"] for error in snapshot["errors"]} == {"source_timeout"}


def test_invalid_yaml_marks_the_deployed_source_invalid():
    snapshot = build_config_snapshot(_inputs(INVALID_CONFIG_INPUT))

    assert snapshot["status"] == "degraded"
    assert snapshot["sources"][0]["status"] == "invalid"
    assert {error["code"] for error in snapshot["errors"]} == {"source_invalid"}


def test_missing_deployed_source_retains_missing_status():
    snapshot = build_config_snapshot(_inputs({**HEALTHY_INPUT, "litellm_yaml": None}, litellm_status="missing"))

    assert snapshot["sources"][0]["status"] == "missing"
    assert {error["code"] for error in snapshot["errors"]} == {"source_missing"}


def test_missing_environment_reference_is_reported_without_its_value():
    snapshot = build_config_snapshot(_inputs(MISSING_ENV_INPUT))

    assert snapshot["environment"] == [{"name": "OPENAI_API_KEY", "present": False}]
    assert any(item["status"] == "warn" for item in snapshot["validation"])
    assert snapshot["status"] == "degraded"


def test_aliases_are_stable_sorted_deduplicated_and_tied_providers_are_sorted():
    fixture = {
        **HEALTHY_INPUT,
        "litellm_yaml": """model_list:
  - model_name: zebra
    litellm_params: {model: anthropic/zebra}
  - model_name: alpha
    litellm_params: {model: openai/alpha}
  - model_name: alpha
    litellm_params: {model: openai/alpha}
""",
        "registry_model_ids": ["zebra", "alpha", "alpha"],
        "runtime_model_ids": ["zebra", "alpha", "alpha"],
    }

    snapshot = build_config_snapshot(_inputs(fixture))

    assert snapshot["models"]["configured"] == ["alpha", "zebra"]
    assert snapshot["models"]["providers"] == [
        {"alias": "alpha", "family": "openai"},
        {"alias": "zebra", "family": "anthropic"},
    ]


def test_runtime_public_prefix_is_removed_without_changing_other_sources():
    snapshot = build_config_snapshot(_inputs({**HEALTHY_INPUT, "runtime_model_ids": ["AI-Gateway:gpt-safe"]}))

    assert snapshot["models"]["configured"] == ["gpt-safe"]
    assert snapshot["models"]["runtime"] == ["gpt-safe"]
    assert snapshot["drift"]["status"] == "clean"


def test_provider_family_is_allowlisted_from_model_identifier_only():
    fixture = {
        **HEALTHY_INPUT,
        "litellm_yaml": """model_list:
  - model_name: safe
    litellm_params:
      model: unsafe-provider/safe
      api_base: https://secret.example/v1
""",
        "registry_model_ids": ["safe"],
        "runtime_model_ids": ["safe"],
    }

    snapshot = build_config_snapshot(_inputs(fixture))

    assert snapshot["models"]["providers"] == [{"alias": "safe", "family": "other"}]


def test_router_projection_is_allowlisted():
    fixture = {
        **HEALTHY_INPUT,
        "litellm_yaml": """model_list: []
router_settings:
  routing_strategy: least-busy
  num_retries: 3
  api_key: sk-do-not-return
  api_base: https://secret.example/v1
""",
        "registry_model_ids": [],
        "runtime_model_ids": [],
    }

    assert build_config_snapshot(_inputs(fixture))["routing"] == {
        "num_retries": 3,
        "routing_strategy": "least-busy",
    }


def test_mcp_projection_contains_only_alias_and_transport_kind():
    fixture = {
        **HEALTHY_INPUT,
        "litellm_yaml": """model_list: []
mcp_servers:
  filesystem:
    command: /home/runner/secret-command
    args: [--token, sk-do-not-return]
    transport: stdio
  remote:
    url: https://secret.example/mcp
    transport: sse
""",
        "registry_model_ids": [],
        "runtime_model_ids": [],
    }

    snapshot = build_config_snapshot(_inputs(fixture))

    assert snapshot["mcp"] == [
        {"alias": "filesystem", "transport": "stdio"},
        {"alias": "remote", "transport": "sse"},
    ]
    assert "secret" not in json.dumps(snapshot)


def test_mcp_projection_omits_unrecognised_transport_values():
    fixture = {
        **HEALTHY_INPUT,
        "litellm_yaml": """model_list: []
mcp_servers:
  safe: {transport: stdio}
  unsafe: {transport: run-local-command}
""",
        "registry_model_ids": [],
        "runtime_model_ids": [],
    }

    assert build_config_snapshot(_inputs(fixture))["mcp"] == [{"alias": "safe", "transport": "stdio"}]


def test_sanitized_source_digest_is_stable_when_only_secrets_change():
    first = build_config_snapshot(_inputs(SECRET_LOOKING_INPUT))
    second = build_config_snapshot(
        _inputs(
            {
                **SECRET_LOOKING_INPUT,
                "litellm_yaml": SECRET_LOOKING_INPUT["litellm_yaml"]
                .replace("sk-do-not-return", "different-secret")
                .replace("secret.example", "another.example"),
            }
        )
    )

    assert first["sources"][0]["digest"] == second["sources"][0]["digest"]


def test_collections_and_strings_are_bounded():
    aliases = [f"model-{number:03d}" for number in range(MAX_ENTRIES + 20)]
    long_alias = "x" * (MAX_STRING + 20)
    snapshot = build_config_snapshot(
        _inputs(
            {
                **HEALTHY_INPUT,
                "litellm_yaml": "model_list: []\n",
                "registry_model_ids": [*aliases, long_alias],
                "runtime_model_ids": [*aliases, long_alias],
            }
        )
    )

    assert len(snapshot["models"]["registry"]) == MAX_ENTRIES
    assert all(len(alias) <= MAX_STRING for alias in snapshot["models"]["registry"])


def test_configured_models_are_deduplicated_sorted_then_capped():
    aliases = [f"model-{number:03d}" for number in range(MAX_ENTRIES + 20)]
    yaml_models = "\n".join(
        f"  - model_name: {alias}\n    litellm_params: {{model: openai/{alias}}}" for alias in reversed(aliases)
    )
    snapshot = build_config_snapshot(
        _inputs(
            {
                **HEALTHY_INPUT,
                "litellm_yaml": f"model_list:\n{yaml_models}\n",
                "registry_model_ids": aliases,
                "runtime_model_ids": aliases,
            }
        )
    )

    assert snapshot["models"]["configured"] == aliases[:MAX_ENTRIES]


def test_depth_eight_redacts_deep_environment_reference():
    nested = "OPENAI_API_KEY"
    for _ in range(MAX_DEPTH + 1):
        nested = {"nested": nested}
    fixture = {
        **HEALTHY_INPUT,
        "litellm_yaml": "model_list: []\nmetadata: " + json.dumps(nested),
        "registry_model_ids": [],
        "runtime_model_ids": [],
    }

    snapshot = build_config_snapshot(_inputs(fixture))

    assert snapshot["environment"] == []
    assert "OPENAI_API_KEY" not in json.dumps(snapshot)
