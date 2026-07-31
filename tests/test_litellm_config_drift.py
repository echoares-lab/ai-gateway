import json
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.ops.validate_litellm_config_drift import compare_configs

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "litellm_config_drift"


def _fixture_config(name: str) -> tuple[dict, dict]:
    yaml_config = yaml.safe_load((FIXTURES / "clean.yaml").read_text(encoding="utf-8"))
    db_snapshot = json.loads((FIXTURES / f"{name}-db.json").read_text(encoding="utf-8"))
    return yaml_config, db_snapshot


def _yaml_config() -> dict:
    return {
        "model_list": [
            {
                "model_name": "gpt-test",
                "litellm_params": {
                    "model": "openai/gpt-test",
                    "api_base": "http://cliproxy:8317/v1",
                    "api_key": "os.environ/CLIPROXY_API_KEY",
                },
            },
            {
                "model_name": "claude-test",
                "litellm_params": {
                    "model": "anthropic/claude-test",
                    "api_base": "http://cliproxy:8317/v1",
                },
            },
        ],
        "general_settings": {"store_model_in_db": True},
        "router_settings": {"routing_strategy": "latency-based-routing"},
    }


def _db_snapshot() -> dict:
    return {
        "models": [
            {
                "model_name": "gpt-test",
                "litellm_params": {
                    "model": "openai/gpt-test",
                    "api_base": "http://cliproxy:8317/v1",
                    "api_key": "os.environ/CLIPROXY_API_KEY",
                },
            },
            {
                "model_name": "claude-test",
                "litellm_params": {
                    "model": "anthropic/claude-test",
                    "api_base": "http://cliproxy:8317/v1",
                },
            },
        ],
        "intentional_overrides": [],
    }


def test_clean_yaml_and_postgres_fixture_have_stable_empty_report() -> None:
    assert compare_configs(_yaml_config(), _db_snapshot()) == []


def test_repository_clean_fixture_is_clean() -> None:
    yaml_config, db_snapshot = _fixture_config("clean")
    assert compare_configs(yaml_config, db_snapshot) == []


def test_repository_drift_fixture_is_nonzero() -> None:
    yaml_config, db_snapshot = _fixture_config("drift")
    assert compare_configs(yaml_config, db_snapshot) == ["model_list[gpt-test].litellm_params.api_base differs"]


def test_repository_override_fixture_is_explicitly_clean() -> None:
    yaml_config, db_snapshot = _fixture_config("override")
    assert compare_configs(yaml_config, db_snapshot) == []


def test_mismatch_reports_exact_setting_path_without_values() -> None:
    db = _db_snapshot()
    db["models"][0]["litellm_params"]["api_base"] = "https://secret.example.invalid"

    errors = compare_configs(_yaml_config(), db)

    assert errors == ["model_list[gpt-test].litellm_params.api_base differs"]
    assert "secret.example" not in " ".join(errors)


def test_known_postgres_override_is_explicit_and_does_not_drift() -> None:
    db = _db_snapshot()
    db["models"][0]["litellm_params"]["api_base"] = "http://runtime-override:8317/v1"
    db["intentional_overrides"] = [{"model_name": "gpt-test", "path": "litellm_params.api_base"}]

    assert compare_configs(_yaml_config(), db) == []


def test_missing_and_unexpected_models_are_reported() -> None:
    db = _db_snapshot()
    db["models"].pop()
    db["models"].append({"model_name": "unexpected", "litellm_params": {"model": "openai/unexpected"}})

    assert compare_configs(_yaml_config(), db) == [
        "model_list[claude-test] is missing from postgres",
        "model_list[unexpected] exists only in postgres",
    ]


def test_cli_returns_nonzero_for_drift_and_json_contains_names_only(tmp_path: Path) -> None:
    yaml_path = tmp_path / "config.yaml"
    db_path = tmp_path / "db.json"
    yaml_path.write_text(
        "model_list:\n  - model_name: gpt-test\n    litellm_params:\n      model: openai/gpt-test\n", encoding="utf-8"
    )
    db = {"models": [{"model_name": "gpt-test", "litellm_params": {"model": "openai/other"}}]}
    db_path.write_text(json.dumps(db), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/ops/validate_litellm_config_drift.py", str(yaml_path), str(db_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "model_list[gpt-test].litellm_params.model differs" in result.stdout
    assert "openai/other" not in result.stdout
