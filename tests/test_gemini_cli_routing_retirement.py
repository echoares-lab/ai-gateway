"""Deployment guardrails for the retired Gemini CLI routing tier."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "litellm-config.yaml"


def _config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def test_model_catalog_has_no_via_gcli_deployments() -> None:
    model_names = [entry["model_name"] for entry in _config()["model_list"]]

    assert not [name for name in model_names if "via-gcli" in name]


def test_fallback_graph_has_no_via_gcli_sources_or_targets() -> None:
    fallback_graph = _config()["litellm_settings"]["fallbacks"]

    references = [
        model
        for rule in fallback_graph
        for source, targets in rule.items()
        for model in (source, *targets)
        if "via-gcli" in model
    ]
    assert not references


def test_policy_fallback_registry_has_no_via_gcli_references() -> None:
    policy_fallback = (ROOT / "services" / "gateway-engine" / "core" / "policy" / "fallback.py").read_text(
        encoding="utf-8"
    )

    assert "via-gcli" not in policy_fallback


def test_deployment_cli_does_not_offer_gemini_cli_oauth() -> None:
    setup_script = (ROOT / "cliproxy-setup.sh").read_text(encoding="utf-8")

    assert "login-gemini" not in setup_script
    assert 'gemini)       "$CLIPROXY_BIN"' not in setup_script


def test_runbook_does_not_advertise_gemini_cli_auth_files() -> None:
    runbook = (ROOT / "docs" / "ops" / "RUNBOOK.md").read_text(encoding="utf-8")

    assert "gemini-{email}-{project}.json" not in runbook
