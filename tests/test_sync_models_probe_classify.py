"""Unit tests for sync-models probe response classification."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLASSIFY_SCRIPT = REPO_ROOT / "scripts" / "sync_models_probe_classify.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from sync_models_probe_classify import (  # noqa: E402
    OUTCOME_MISSING_MODEL,
    OUTCOME_PRESERVE,
    OUTCOME_SUCCESS,
    OUTCOME_TRANSIENT,
    classify_probe_response,
    probe_exit_code,
    remove_model_block_from_litellm_config,
    should_remove_model_from_config,
)


@pytest.mark.parametrize(
    ("http_code", "body", "expected"),
    [
        ("200", '{"choices":[{"message":{"content":"hi"}}]}', OUTCOME_SUCCESS),
        ("429", '{"error":{"message":"rate limit exceeded"}}', OUTCOME_TRANSIENT),
        ("503", '{"error":{"message":"service unavailable"}}', OUTCOME_TRANSIENT),
        ("502", '{"error":{"message":"bad gateway"}}', OUTCOME_TRANSIENT),
        ("504", '{"error":{"message":"gateway timeout"}}', OUTCOME_TRANSIENT),
        ("404", '{"error":{"message":"model not found"}}', OUTCOME_MISSING_MODEL),
        ("400", '{"error":{"message":"model not found"}}', OUTCOME_MISSING_MODEL),
        ("403", '{"error":{"message":"forbidden"}}', OUTCOME_PRESERVE),
        ("401", '{"error":{"message":"invalid api key"}}', OUTCOME_PRESERVE),
        ("400", '{"error":{"message":"quota exceeded for model"}}', OUTCOME_TRANSIENT),
        ("200", '{"error":{"message":"resource exhausted, try again later"}}', OUTCOME_TRANSIENT),
        ("200", '{"error":{"type":"rate_limit_error"}}', OUTCOME_TRANSIENT),
        ("200", '{"choices":[]}', OUTCOME_PRESERVE),
        ("500", '{"error":{"message":"internal error"}}', OUTCOME_TRANSIENT),
        ("", "", OUTCOME_TRANSIENT),
        ("000", "", OUTCOME_TRANSIENT),
    ],
)
def test_classify_probe_response(http_code: str, body: str, expected: str) -> None:
    assert classify_probe_response(http_code, body) == expected


def test_cli_wrapper_matches_direct_call() -> None:
    body = '{"error":{"message":"429 Too Many Requests"}}'
    direct = classify_probe_response("400", body)
    proc = subprocess.run(
        [sys.executable, str(CLASSIFY_SCRIPT), "400"],
        input=body,
        text=True,
        capture_output=True,
        check=True,
    )
    assert proc.stdout.strip() == direct


@pytest.mark.parametrize(
    ("http_code", "body", "should_remove"),
    [
        ("429", '{"error":{"message":"rate limit exceeded"}}', False),
        ("401", '{"error":{"message":"invalid api key"}}', False),
        ("403", '{"error":{"message":"forbidden"}}', False),
        ("503", '{"error":{"message":"service unavailable"}}', False),
        ("404", '{"error":{"message":"model not found"}}', True),
    ],
)
def test_regression_probe_removal_decision(
    http_code: str, body: str, should_remove: bool
) -> None:
    """429 quota cooldown must not remove models; 404 may."""
    outcome = classify_probe_response(http_code, body)
    exit_code = probe_exit_code(outcome)
    assert should_remove_model_from_config(exit_code) is should_remove


def test_regression_429_preserves_litellm_config_entry(tmp_path) -> None:
    config_path = tmp_path / "litellm-config.yaml"
    alias = "gemini-3-flash"
    config_path.write_text(
        f"""model_list:
  - model_name: {alias}
    litellm_params:
      model: openai/gemini-3-flash
      api_base: http://cliproxy:8317/v1
      api_key: os.environ/CLIPROXY_API_KEY
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
""",
        encoding="utf-8",
    )

    outcome = classify_probe_response(
        "429", '{"error":{"message":"quota cooldown — try again later"}}'
    )
    assert outcome == OUTCOME_TRANSIENT
    assert should_remove_model_from_config(probe_exit_code(outcome)) is False

    content = config_path.read_text(encoding="utf-8")
    assert f"model_name: {alias}" in content


def test_404_removes_litellm_config_entry(tmp_path) -> None:
    config_path = tmp_path / "litellm-config.yaml"
    alias = "dead-model"
    config_path.write_text(
        f"""model_list:
  - model_name: {alias}
    litellm_params:
      model: openai/dead.model
      api_base: http://cliproxy:8317/v1
      api_key: os.environ/CLIPROXY_API_KEY
  - model_name: keep-me
    litellm_params:
      model: openai/keep.me
      api_base: http://cliproxy:8317/v1
      api_key: os.environ/CLIPROXY_API_KEY
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
""",
        encoding="utf-8",
    )

    outcome = classify_probe_response("404", '{"error":{"message":"model not found"}}')
    assert outcome == OUTCOME_MISSING_MODEL
    assert should_remove_model_from_config(probe_exit_code(outcome)) is True

    remove_model_block_from_litellm_config(str(config_path), alias)
    content = config_path.read_text(encoding="utf-8")
    assert f"model_name: {alias}" not in content
    assert "model_name: keep-me" in content
