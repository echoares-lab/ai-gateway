"""Deployment guardrails for the retired Gemini CLI routing tier."""

import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "litellm-config.yaml"

# The auth-file naming the retired Gemini CLI OAuth tier used to advertise.
RETIRED_AUTH_FILE_PATTERN = "gemini-{email}-{project}.json"


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


def test_repository_does_not_advertise_gemini_cli_auth_files() -> None:
    """No tracked file may advertise the retired Gemini CLI auth-file naming.

    This previously read only docs/ops/RUNBOOK.md. That runbook now lives in the
    vault (Master-Policy §1.6), so the guard scans every git-tracked file
    instead — a strictly wider check that no longer depends on prose staying in
    the repository.
    """
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout.decode()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        pytest.skip("git is unavailable; cannot enumerate tracked files")

    offenders = []
    for name in filter(None, tracked.split("\0")):
        path = ROOT / name
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable file: nothing to advertise
        if RETIRED_AUTH_FILE_PATTERN in text and path.name != Path(__file__).name:
            offenders.append(name)

    assert not offenders, f"retired Gemini CLI auth-file naming still advertised in: {offenders}"
