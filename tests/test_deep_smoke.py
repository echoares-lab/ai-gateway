"""Offline tests for scripts/ops/deep-smoke.sh and scripts/ops/deep_smoke.py.

Everything here runs without network access or a live gateway/kube cluster:
curl and kubectl are replaced with fakes under tests/fixtures/deep_smoke/,
driven entirely through env vars. See docs/superpowers/specs/
2026-07-17-staging-deep-smoke-design.md and issue #398 (bundle #396).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEEP_SMOKE_SH = REPO_ROOT / "scripts" / "ops" / "deep-smoke.sh"
DEEP_SMOKE_PY = REPO_ROOT / "scripts" / "ops" / "deep_smoke.py"
FAKE_CURL = REPO_ROOT / "tests" / "fixtures" / "deep_smoke" / "fake_curl.sh"
FAKE_KUBECTL = REPO_ROOT / "tests" / "fixtures" / "deep_smoke" / "fake_kubectl.sh"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "ops"))
from deep_smoke import (  # noqa: E402
    check_completion_payload,
    check_models_payload,
    check_pods_payload,
    check_version_payload,
    parse_json,
)

# ---------------------------------------------------------------------------
# Pure function tests (imported directly)
# ---------------------------------------------------------------------------


def test_parse_json_empty_body() -> None:
    payload, err = parse_json("")
    assert payload is None
    assert err == "empty response body"


def test_parse_json_invalid() -> None:
    payload, err = parse_json("{not json")
    assert payload is None
    assert err is not None and "invalid JSON" in err


def test_parse_json_valid() -> None:
    payload, err = parse_json('{"a": 1}')
    assert err is None
    assert payload == {"a": 1}


def test_check_version_payload_pass() -> None:
    outcome = check_version_payload({"version": "1.0", "git_sha": "abc", "display_version": "1.0 (abc)"})
    assert outcome.status == "pass"
    assert outcome.exit_code == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"version": "1.0"},  # missing git_sha, display_version
        {"git_sha": "abc", "display_version": "x"},  # missing version
        [],  # not an object
        "not-a-dict",
    ],
)
def test_check_version_payload_fail(payload: object) -> None:
    outcome = check_version_payload(payload)
    assert outcome.status == "fail"
    assert outcome.exit_code == 1


def test_check_models_payload_pass() -> None:
    outcome = check_models_payload({"data": [{"id": "AI-Gateway:claude-sonnet-4-6"}]})
    assert outcome.status == "pass"


def test_check_models_payload_empty_list_fails() -> None:
    outcome = check_models_payload({"data": []})
    assert outcome.status == "fail"
    assert "zero models" in outcome.message


def test_check_models_payload_missing_data_fails() -> None:
    outcome = check_models_payload({"unexpected": True})
    assert outcome.status == "fail"


def test_check_completion_payload_pass() -> None:
    outcome = check_completion_payload({"choices": [{"message": {"content": "pong"}}]})
    assert outcome.status == "pass"


def test_check_completion_payload_error_field_fails() -> None:
    outcome = check_completion_payload({"error": {"message": "rate limited"}})
    assert outcome.status == "fail"
    assert "rate limited" in outcome.message


def test_check_completion_payload_no_choices_fails() -> None:
    outcome = check_completion_payload({"choices": []})
    assert outcome.status == "fail"


def test_check_completion_payload_empty_content_warns() -> None:
    outcome = check_completion_payload({"choices": [{"message": {"content": ""}}]})
    assert outcome.status == "warn"
    assert outcome.exit_code == 2


def test_check_pods_payload_all_ready() -> None:
    payload = {
        "items": [
            {
                "metadata": {"name": "gateway-engine-abc"},
                "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
            },
            {
                "metadata": {"name": "migration-job-xyz"},
                "status": {"phase": "Succeeded"},
            },
        ]
    }
    outcome = check_pods_payload(payload)
    assert outcome.status == "pass"


def test_check_pods_payload_not_ready_fails() -> None:
    payload = {
        "items": [
            {
                "metadata": {"name": "litellm-0"},
                "status": {"phase": "Pending", "conditions": []},
            }
        ]
    }
    outcome = check_pods_payload(payload)
    assert outcome.status == "fail"
    assert "litellm-0" in outcome.message


def test_check_pods_payload_allowlist_skips_not_ready() -> None:
    payload = {
        "items": [
            {
                "metadata": {"name": "flaky-canary-0"},
                "status": {"phase": "CrashLoopBackOff", "conditions": []},
            }
        ]
    }
    outcome = check_pods_payload(payload, allowlist=["flaky-canary"])
    assert outcome.status == "pass"
    assert "allowlisted skipped" in outcome.message


def test_check_pods_payload_empty_namespace_warns() -> None:
    outcome = check_pods_payload({"items": []})
    assert outcome.status == "warn"


def test_check_pods_payload_missing_items_fails() -> None:
    outcome = check_pods_payload({"unexpected": True})
    assert outcome.status == "fail"


# ---------------------------------------------------------------------------
# CLI wrapper tests (subprocess — matches how deep-smoke.sh invokes the helper)
# ---------------------------------------------------------------------------


def _run_helper(args: list[str], stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DEEP_SMOKE_PY), *args],
        input=stdin,
        text=True,
        capture_output=True,
    )


def test_cli_check_version_pass_exit_code() -> None:
    proc = _run_helper(["check-version"], '{"version":"1.0","git_sha":"a","display_version":"1.0"}')
    assert proc.returncode == 0
    assert "version=1.0" in proc.stdout


def test_cli_check_version_fail_exit_code() -> None:
    proc = _run_helper(["check-version"], '{"version":"1.0"}')
    assert proc.returncode == 1


def test_cli_check_models_fail_on_bad_json() -> None:
    proc = _run_helper(["check-models"], "not json")
    assert proc.returncode == 1
    assert "invalid JSON" in proc.stdout


def test_cli_check_pods_allowlist_flag() -> None:
    payload = '{"items":[{"metadata":{"name":"canary-1"},"status":{"phase":"Pending","conditions":[]}}]}'
    proc = _run_helper(["check-pods", "--allowlist", "canary"], payload)
    assert proc.returncode == 0
    assert "allowlisted skipped" in proc.stdout


def test_cli_unknown_subcommand_exits_2() -> None:
    proc = _run_helper(["bogus-command"], "")
    assert proc.returncode == 2


def test_cli_no_args_exits_2() -> None:
    proc = subprocess.run([sys.executable, str(DEEP_SMOKE_PY)], capture_output=True, text=True)
    assert proc.returncode == 2


# ---------------------------------------------------------------------------
# Shell script tests (bash -n + full runs against fakes, no live network)
# ---------------------------------------------------------------------------


def test_bash_syntax_check() -> None:
    proc = subprocess.run(["bash", "-n", str(DEEP_SMOKE_SH)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def _run_deep_smoke(args: list[str], env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    env["DEEP_SMOKE_CURL_BIN"] = str(FAKE_CURL)
    env["DEEP_SMOKE_KUBECTL_BIN"] = str(FAKE_KUBECTL)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(DEEP_SMOKE_SH), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )


def test_help_exits_zero_and_prints_usage() -> None:
    proc = _run_deep_smoke(["--help"])
    assert proc.returncode == 0
    assert "deep-smoke.sh" in proc.stdout
    assert "--quick" in proc.stdout


def test_unknown_flag_exits_2() -> None:
    proc = _run_deep_smoke(["--bogus-flag"])
    assert proc.returncode == 2
    assert "unknown argument" in proc.stderr


def test_invalid_env_exits_2() -> None:
    proc = _run_deep_smoke(["--env", "nope"])
    assert proc.returncode == 2
    assert "--env must be" in proc.stderr


def test_full_mode_not_implemented_exits_3() -> None:
    proc = _run_deep_smoke(["--env", "staging", "--full"])
    assert proc.returncode == 3
    assert "not yet implemented" in proc.stderr
    assert "#396" in proc.stderr


def test_quick_mode_all_pass() -> None:
    pods_json = (
        '{"items":[{"metadata":{"name":"gateway-engine-abc"},'
        '"status":{"phase":"Running","conditions":[{"type":"Ready","status":"True"}]}}]}'
    )
    proc = _run_deep_smoke(
        ["--env", "staging", "--quick"],
        env_overrides={"FAKE_PODS_JSON": pods_json},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Overall: PASS" in proc.stdout
    for check in ("health", "ready", "version", "models", "completion", "pods"):
        assert f"| {check} | PASS |" in proc.stdout


def test_quick_mode_default_is_quick_and_staging() -> None:
    """No --env/--quick/--full flags: defaults to staging + quick."""
    proc = _run_deep_smoke([])
    assert "env=staging mode=quick" in proc.stdout


def test_quick_mode_check_order() -> None:
    proc = _run_deep_smoke(["--env", "staging", "--quick"])
    rows = [line for line in proc.stdout.splitlines() if line.startswith("| ") and " | " in line[2:]]
    check_names = [row.split("|")[1].strip() for row in rows if row.split("|")[1].strip() != "Check"]
    assert check_names == ["health", "ready", "version", "models", "completion", "pods"]


def test_quick_mode_health_failure_propagates_to_overall_and_exit_1() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--quick"],
        env_overrides={"FAKE_HEALTH_CODE": "503"},
    )
    assert proc.returncode == 1
    assert "| health | FAIL | GET /health -> 503 |" in proc.stdout
    assert "Overall: FAIL" in proc.stdout


def test_quick_mode_completion_error_body_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--quick"],
        env_overrides={"FAKE_COMPLETION_BODY": '{"error":{"message":"rate limited"}}'},
    )
    assert proc.returncode == 1
    assert "rate limited" in proc.stdout


def test_quick_mode_missing_kubectl_warns_not_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--quick"],
        env_overrides={"DEEP_SMOKE_KUBECTL_BIN": "/nonexistent/kubectl-binary-for-tests"},
    )
    assert proc.returncode == 0
    assert "| pods | WARN |" in proc.stdout
    assert "Overall: WARN" in proc.stdout


def test_quick_mode_missing_kubectl_with_strict_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--quick", "--strict"],
        env_overrides={"DEEP_SMOKE_KUBECTL_BIN": "/nonexistent/kubectl-binary-for-tests"},
    )
    assert proc.returncode == 1
    assert "| pods | FAIL |" in proc.stdout
    assert "Overall: FAIL" in proc.stdout


def test_quick_mode_skip_pods_env_var() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--quick"],
        env_overrides={"DEEP_SMOKE_SKIP_PODS": "1"},
    )
    assert proc.returncode == 0
    assert "| pods | WARN | skipped via DEEP_SMOKE_SKIP_PODS=1 |" in proc.stdout


def test_prod_env_uses_prod_defaults() -> None:
    proc = _run_deep_smoke(["--env", "prod", "--quick"])
    assert "env=prod mode=quick" in proc.stdout


def test_pods_allowlist_env_var_skips_bad_pod() -> None:
    pods_json = '{"items":[{"metadata":{"name":"canary-flaky-1"},"status":{"phase":"Pending","conditions":[]}}]}'
    proc = _run_deep_smoke(
        ["--env", "staging", "--quick"],
        env_overrides={"FAKE_PODS_JSON": pods_json, "DEEP_SMOKE_PODS_ALLOWLIST": "canary-flaky"},
    )
    assert proc.returncode == 0
    assert "| pods | PASS |" in proc.stdout
