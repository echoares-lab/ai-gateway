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


def test_accepted_source_errors_force_non_ok_source_statuses_and_unknown_drift():
    expected_statuses = {
        "source_missing": "missing",
        "source_invalid": "invalid",
        "source_timeout": "unavailable",
        "source_unavailable": "unavailable",
    }

    for error_code, expected_status in expected_statuses.items():
        snapshot = build_config_snapshot(
            _inputs(HEALTHY_INPUT, source_errors=(("runtime-visible-models", error_code),))
        )

        assert snapshot["status"] == "degraded"
        assert snapshot["drift"]["status"] == "unknown"
        assert (
            next(source for source in snapshot["sources"] if source["id"] == "runtime-visible-models")["status"]
            == expected_status
        )


def test_duplicate_source_errors_use_the_canonical_error_to_derive_status():
    first = build_config_snapshot(
        _inputs(
            HEALTHY_INPUT,
            source_errors=(
                ("runtime-visible-models", "source_timeout"),
                ("runtime-visible-models", "source_invalid"),
            ),
        )
    )
    second = build_config_snapshot(
        _inputs(
            HEALTHY_INPUT,
            source_errors=(
                ("runtime-visible-models", "source_invalid"),
                ("runtime-visible-models", "source_timeout"),
            ),
        )
    )

    assert first == second
    assert first["errors"] == [{"source": "runtime-visible-models", "code": "source_invalid"}]
    assert (
        next(source for source in first["sources"] if source["id"] == "runtime-visible-models")["status"] == "invalid"
    )


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


def test_overlong_environment_reference_is_omitted_before_output_and_digest():
    first_name = "A" * (MAX_STRING + 1)
    second_name = "B" * (MAX_STRING + 1)
    first = build_config_snapshot(
        _inputs(
            {
                **HEALTHY_INPUT,
                "litellm_yaml": f"model_list: []\nmetadata: os.environ/{first_name}\n",
                "registry_model_ids": [],
                "runtime_model_ids": [],
            }
        )
    )
    second = build_config_snapshot(
        _inputs(
            {
                **HEALTHY_INPUT,
                "litellm_yaml": f"model_list: []\nmetadata: os.environ/{second_name}\n",
                "registry_model_ids": [],
                "runtime_model_ids": [],
            }
        )
    )

    assert first["environment"] == []
    assert first == second
    assert first_name not in json.dumps(first)


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


def test_router_projection_rejects_command_like_strings():
    fixture = {
        **HEALTHY_INPUT,
        "litellm_yaml": """model_list: []
router_settings:
  routing_strategy: curl https://secret.example/run
  allowed_fails: rm -rf /
  cooldown_time: etc/keys
  num_retries: 3
""",
        "registry_model_ids": [],
        "runtime_model_ids": [],
    }

    assert build_config_snapshot(_inputs(fixture))["routing"] == {"num_retries": 3}


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


def test_public_aliases_reject_credentials_paths_jwts_and_commands_from_every_projection():
    good_alias = "gpt-4o.mini_2026:preview+canary"
    rejected_aliases = (
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature1234",
        "etc/keys",
        "rm -rf /",
    )
    fixture = {
        **HEALTHY_INPUT,
        "litellm_yaml": "\n".join(
            [
                "model_list:",
                f"  - model_name: {good_alias}",
                f"    litellm_params: {{model: openai/{good_alias}}}",
                *[
                    f"  - model_name: {alias}\n    litellm_params: {{model: openai/gpt-safe}}"
                    for alias in rejected_aliases
                ],
                "fallbacks:",
                *[f"  - {alias}: [{good_alias}]" for alias in rejected_aliases],
                f"  - {good_alias}: [{', '.join(rejected_aliases)}]",
                "mcp_servers:",
                f"  {good_alias}: {{transport: stdio}}",
                *[f"  {alias}: {{transport: sse}}" for alias in rejected_aliases],
                "",
            ]
        ),
        "registry_model_ids": [good_alias, *rejected_aliases],
        "runtime_model_ids": [f"AI-Gateway:{good_alias}", *(f"AI-Gateway:{alias}" for alias in rejected_aliases)],
    }

    first = build_config_snapshot(_inputs(fixture))
    changed_fixture = {
        **fixture,
        "litellm_yaml": fixture["litellm_yaml"].replace(
            "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890", "ghp_ZYXWVUTSRQPONMLKJIHGFEDCBA9876543210"
        ),
        "registry_model_ids": [good_alias, *(f"changed-{index}/keys" for index in range(len(rejected_aliases)))],
        "runtime_model_ids": [
            f"AI-Gateway:{good_alias}",
            *(f"AI-Gateway:changed-{index}/keys" for index in range(len(rejected_aliases))),
        ],
    }
    second = build_config_snapshot(_inputs(changed_fixture))

    assert first["models"]["configured"] == [good_alias]
    assert first["models"]["registry"] == [good_alias]
    assert first["models"]["runtime"] == [good_alias]
    assert first["models"]["fallbacks"] == []
    assert first["mcp"] == [{"alias": good_alias, "transport": "stdio"}]
    assert first == second
    serialized = json.dumps(first)
    assert all(alias not in serialized for alias in rejected_aliases)


def test_overlong_aliases_survive_collection_caps_but_are_rejected_everywhere():
    aliases = [f"model-{number:03d}" for number in range(MAX_ENTRIES - 1)]
    long_alias = "z" * (MAX_STRING + 20)
    yaml_models = "\n".join(
        f"  - model_name: {alias}\n    litellm_params: {{model: openai/{alias}}}" for alias in [*aliases, long_alias]
    )
    snapshot = build_config_snapshot(
        _inputs(
            {
                **HEALTHY_INPUT,
                "litellm_yaml": f"""model_list:
{yaml_models}
fallbacks:
  - {long_alias}: [model-000]
mcp_servers:
  {long_alias}: {{transport: stdio}}
""",
                "registry_model_ids": [*aliases, long_alias],
                "runtime_model_ids": [*aliases, long_alias],
            }
        )
    )

    assert snapshot["models"]["configured"] == aliases
    assert len(snapshot["models"]["registry"]) == MAX_ENTRIES - 1
    assert snapshot["models"]["registry"] == aliases
    assert snapshot["models"]["runtime"] == aliases
    assert snapshot["models"]["fallbacks"] == []
    assert snapshot["mcp"] == []
    assert long_alias not in json.dumps(snapshot)


def test_rejected_alias_collisions_and_duplicate_source_errors_are_order_independent():
    long_prefix = "z" * MAX_STRING
    first_yaml = f"""model_list: []
fallbacks:
  - {long_prefix}a: [model-safe]
  - {long_prefix}b: [model-safe]
mcp_servers:
  {long_prefix}a: {{transport: stdio}}
  {long_prefix}b: {{transport: sse}}
"""
    second_yaml = f"""model_list: []
fallbacks:
  - {long_prefix}b: [model-safe]
  - {long_prefix}a: [model-safe]
mcp_servers:
  {long_prefix}b: {{transport: sse}}
  {long_prefix}a: {{transport: stdio}}
"""
    first = build_config_snapshot(
        _inputs(
            {**HEALTHY_INPUT, "litellm_yaml": first_yaml, "registry_model_ids": [], "runtime_model_ids": []},
            source_errors=(("litellm-config", "source_timeout"), ("litellm-config", "source_invalid")),
        )
    )
    second = build_config_snapshot(
        _inputs(
            {**HEALTHY_INPUT, "litellm_yaml": second_yaml, "registry_model_ids": [], "runtime_model_ids": []},
            source_errors=(("litellm-config", "source_invalid"), ("litellm-config", "source_timeout")),
        )
    )

    assert first == second
    assert first["models"]["fallbacks"] == []
    assert first["mcp"] == []
    assert first["errors"] == [{"source": "litellm-config", "code": "source_invalid"}]


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
