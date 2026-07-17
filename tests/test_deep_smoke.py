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
    check_admin_credentials_payload,
    check_admin_quota_payload,
    check_admin_status_payload,
    check_completion_payload,
    check_messages_payload,
    check_models_payload,
    check_pods_payload,
    check_responses_payload,
    check_stream_payload,
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


# ---------------------------------------------------------------------------
# --full: /v1/responses shape (check_responses_payload)
# ---------------------------------------------------------------------------


def test_check_responses_payload_pass() -> None:
    outcome = check_responses_payload(
        {
            "object": "response",
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "pong"}]}],
        }
    )
    assert outcome.status == "pass"
    assert outcome.exit_code == 0


def test_check_responses_payload_error_field_fails() -> None:
    outcome = check_responses_payload({"error": {"message": "boom"}})
    assert outcome.status == "fail"
    assert "boom" in outcome.message


def test_check_responses_payload_missing_output_fails() -> None:
    outcome = check_responses_payload({"status": "completed"})
    assert outcome.status == "fail"
    assert "output" in outcome.message


def test_check_responses_payload_empty_output_array_fails() -> None:
    outcome = check_responses_payload({"status": "completed", "output": []})
    assert outcome.status == "fail"


def test_check_responses_payload_empty_text_warns() -> None:
    outcome = check_responses_payload(
        {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": ""}]}]}
    )
    assert outcome.status == "warn"


def test_check_responses_payload_not_a_dict_fails() -> None:
    outcome = check_responses_payload(["not", "a", "dict"])
    assert outcome.status == "fail"


# ---------------------------------------------------------------------------
# --full: /v1/messages shape (check_messages_payload)
# ---------------------------------------------------------------------------


def test_check_messages_payload_pass() -> None:
    outcome = check_messages_payload(
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "pong"}],
            "stop_reason": "end_turn",
        }
    )
    assert outcome.status == "pass"
    assert outcome.exit_code == 0


def test_check_messages_payload_error_type_fails() -> None:
    outcome = check_messages_payload({"type": "error", "error": {"message": "rate limited"}})
    assert outcome.status == "fail"
    assert "rate limited" in outcome.message


def test_check_messages_payload_missing_content_fails() -> None:
    outcome = check_messages_payload({"type": "message", "role": "assistant"})
    assert outcome.status == "fail"


def test_check_messages_payload_empty_content_array_fails() -> None:
    outcome = check_messages_payload({"type": "message", "content": []})
    assert outcome.status == "fail"


def test_check_messages_payload_no_text_blocks_warns() -> None:
    outcome = check_messages_payload({"type": "message", "content": [{"type": "tool_use", "name": "x", "input": {}}]})
    assert outcome.status == "warn"


def test_check_messages_payload_not_a_dict_fails() -> None:
    outcome = check_messages_payload("not-a-dict")
    assert outcome.status == "fail"


# ---------------------------------------------------------------------------
# --full: SSE streaming (check_stream_payload)
# ---------------------------------------------------------------------------


def test_check_stream_payload_pass_with_done_and_content() -> None:
    text = (
        'data: {"choices":[{"delta":{"content":"pong"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )
    outcome = check_stream_payload(text)
    assert outcome.status == "pass"
    assert outcome.exit_code == 0


def test_check_stream_payload_pass_without_done_but_finish_reason() -> None:
    """Some providers omit the [DONE] sentinel; a terminal finish_reason is enough."""
    text = 'data: {"choices":[{"delta":{"content":"pong"},"finish_reason":"stop"}]}\n\n'
    outcome = check_stream_payload(text)
    assert outcome.status == "pass"


def test_check_stream_payload_empty_body_fails() -> None:
    outcome = check_stream_payload("")
    assert outcome.status == "fail"
    assert "empty" in outcome.message


def test_check_stream_payload_no_data_lines_fails() -> None:
    outcome = check_stream_payload("not an SSE stream at all")
    assert outcome.status == "fail"
    assert "no 'data:' lines" in outcome.message


def test_check_stream_payload_no_finish_signal_fails() -> None:
    """Chunk(s) present but the stream cuts off with neither [DONE] nor finish_reason."""
    text = 'data: {"choices":[{"delta":{"content":"pong"},"finish_reason":null}]}\n\n'
    outcome = check_stream_payload(text)
    assert outcome.status == "fail"
    assert "without [DONE]" in outcome.message


def test_check_stream_payload_no_content_warns() -> None:
    text = 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    outcome = check_stream_payload(text)
    assert outcome.status == "warn"


def test_check_stream_payload_error_chunk_fails() -> None:
    text = 'data: {"error":{"message":"rate limited"}}\n\n'
    outcome = check_stream_payload(text)
    assert outcome.status == "fail"
    assert "rate limited" in outcome.message


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
# --full: read-mostly admin checks (issue #400, bundle #396)
# ---------------------------------------------------------------------------


def test_check_admin_status_payload_pass() -> None:
    outcome = check_admin_status_payload({"schema_version": "admin-console.v1", "panels": {}})
    assert outcome.status == "pass"
    assert outcome.exit_code == 0


def test_check_admin_status_payload_error_key_fails() -> None:
    outcome = check_admin_status_payload({"error": "boom"})
    assert outcome.status == "fail"
    assert "boom" in outcome.message


def test_check_admin_status_payload_not_a_dict_fails() -> None:
    outcome = check_admin_status_payload(["not", "a", "dict"])
    assert outcome.status == "fail"


def test_check_admin_credentials_payload_pass_empty_list() -> None:
    outcome = check_admin_credentials_payload({"credentials": []})
    assert outcome.status == "pass"


def test_check_admin_credentials_payload_pass_with_records() -> None:
    outcome = check_admin_credentials_payload(
        {"credentials": [{"id": "cred-1", "provider": "anthropic"}, {"id": "cred-2", "provider": "openai"}]}
    )
    assert outcome.status == "pass"
    assert "2 credential(s)" in outcome.message


def test_check_admin_credentials_payload_error_field_fails() -> None:
    outcome = check_admin_credentials_payload({"error": {"message": "unauthorized"}})
    assert outcome.status == "fail"
    assert "unauthorized" in outcome.message


def test_check_admin_credentials_payload_non_list_credentials_fails() -> None:
    outcome = check_admin_credentials_payload({"credentials": "not-a-list"})
    assert outcome.status == "fail"


def test_check_admin_credentials_payload_not_a_dict_fails() -> None:
    outcome = check_admin_credentials_payload("not-a-dict")
    assert outcome.status == "fail"


def test_check_admin_quota_payload_pass_minimal_object() -> None:
    """Soft contract: ANY JSON object passes — no field contracts asserted."""
    outcome = check_admin_quota_payload({})
    assert outcome.status == "pass"
    assert outcome.exit_code == 0


def test_check_admin_quota_payload_pass_with_status_and_accounts() -> None:
    outcome = check_admin_quota_payload({"status": "ok", "accounts": [{"credential_id": "cred-1"}]})
    assert outcome.status == "pass"
    assert "1 account(s)" in outcome.message


def test_check_admin_quota_payload_pass_even_with_unexpected_status_value() -> None:
    """Soft: an unexpected 'status' value is noted but never fails/warns."""
    outcome = check_admin_quota_payload({"status": "degraded"})
    assert outcome.status == "pass"
    assert "not asserted" in outcome.message


def test_check_admin_quota_payload_pass_even_with_non_list_accounts() -> None:
    """Soft: a malformed 'accounts' field is noted but never fails/warns."""
    outcome = check_admin_quota_payload({"accounts": "not-a-list"})
    assert outcome.status == "pass"
    assert "not asserted" in outcome.message


def test_check_admin_quota_payload_not_a_dict_fails() -> None:
    """The only hard requirement: a JSON object body."""
    outcome = check_admin_quota_payload(["not", "a", "dict"])
    assert outcome.status == "fail"


def test_check_admin_quota_payload_string_fails() -> None:
    outcome = check_admin_quota_payload("not-a-dict")
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


def test_cli_check_responses_pass_exit_code() -> None:
    payload = '{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"pong"}]}]}'
    proc = _run_helper(["check-responses"], payload)
    assert proc.returncode == 0


def test_cli_check_responses_fail_on_error_field() -> None:
    proc = _run_helper(["check-responses"], '{"error":{"message":"boom"}}')
    assert proc.returncode == 1
    assert "boom" in proc.stdout


def test_cli_check_messages_pass_exit_code() -> None:
    proc = _run_helper(["check-messages"], '{"type":"message","content":[{"type":"text","text":"pong"}]}')
    assert proc.returncode == 0


def test_cli_check_messages_fail_on_error_type() -> None:
    proc = _run_helper(["check-messages"], '{"type":"error","error":{"message":"nope"}}')
    assert proc.returncode == 1


def test_cli_check_stream_pass_exit_code() -> None:
    text = 'data: {"choices":[{"delta":{"content":"pong"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    proc = _run_helper(["check-stream"], text)
    assert proc.returncode == 0


def test_cli_check_stream_fail_on_empty_body() -> None:
    proc = _run_helper(["check-stream"], "")
    assert proc.returncode == 1


def test_cli_check_pods_allowlist_flag() -> None:
    payload = '{"items":[{"metadata":{"name":"canary-1"},"status":{"phase":"Pending","conditions":[]}}]}'
    proc = _run_helper(["check-pods", "--allowlist", "canary"], payload)
    assert proc.returncode == 0
    assert "allowlisted skipped" in proc.stdout


def test_cli_check_admin_status_pass_exit_code() -> None:
    proc = _run_helper(["check-admin-status"], '{"schema_version":"admin-console.v1"}')
    assert proc.returncode == 0


def test_cli_check_admin_status_fail_on_bad_json() -> None:
    proc = _run_helper(["check-admin-status"], "not json")
    assert proc.returncode == 1


def test_cli_check_admin_credentials_pass_exit_code() -> None:
    proc = _run_helper(["check-admin-credentials"], '{"credentials":[]}')
    assert proc.returncode == 0


def test_cli_check_admin_credentials_fail_on_error() -> None:
    proc = _run_helper(["check-admin-credentials"], '{"error":"nope"}')
    assert proc.returncode == 1


def test_cli_check_admin_quota_pass_on_any_object() -> None:
    proc = _run_helper(["check-admin-quota"], '{"anything":"goes"}')
    assert proc.returncode == 0


def test_cli_check_admin_quota_fail_on_non_object() -> None:
    proc = _run_helper(["check-admin-quota"], "[1, 2, 3]")
    assert proc.returncode == 1


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


# ---------------------------------------------------------------------------
# --full mode: API shapes, streaming, provider families
# ---------------------------------------------------------------------------


def test_full_mode_all_pass() -> None:
    pods_json = (
        '{"items":[{"metadata":{"name":"gateway-engine-abc"},'
        '"status":{"phase":"Running","conditions":[{"type":"Ready","status":"True"}]}}]}'
    )
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_PODS_JSON": pods_json},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Overall: PASS" in proc.stdout
    for check in (
        "health",
        "ready",
        "version",
        "models",
        "completion",
        "pods",
        "responses_shape",
        "messages_shape",
        "stream",
        "provider_claude",
        "provider_gpt",
        "provider_gemini",
        "admin_status",
        "admin_credentials",
        "admin_quota",
    ):
        assert f"| {check} | PASS |" in proc.stdout, f"missing PASS row for {check}\n{proc.stdout}"


def test_full_mode_check_order_includes_quick_then_full_checks() -> None:
    proc = _run_deep_smoke(["--env", "staging", "--full"])
    rows = [line for line in proc.stdout.splitlines() if line.startswith("| ") and " | " in line[2:]]
    check_names = [row.split("|")[1].strip() for row in rows if row.split("|")[1].strip() != "Check"]
    assert check_names == [
        "health",
        "ready",
        "version",
        "models",
        "completion",
        "pods",
        "responses_shape",
        "messages_shape",
        "stream",
        "provider_claude",
        "provider_gpt",
        "provider_gemini",
        "admin_status",
        "admin_credentials",
        "admin_quota",
    ]


def test_full_mode_responses_shape_failure_propagates() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_RESPONSES_BODY": '{"error":{"message":"boom"}}'},
    )
    assert proc.returncode == 1
    assert "| responses_shape | FAIL |" in proc.stdout
    assert "boom" in proc.stdout
    assert "Overall: FAIL" in proc.stdout


def test_full_mode_responses_shape_http_error_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_RESPONSES_CODE": "500"},
    )
    assert proc.returncode == 1
    assert "| responses_shape | FAIL | POST /v1/responses" in proc.stdout


def test_full_mode_messages_shape_failure_propagates() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_MESSAGES_BODY": '{"type":"error","error":{"message":"nope"}}'},
    )
    assert proc.returncode == 1
    assert "| messages_shape | FAIL |" in proc.stdout
    assert "nope" in proc.stdout


def test_full_mode_stream_failure_propagates() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_STREAM_BODY": "not an SSE stream at all"},
    )
    assert proc.returncode == 1
    assert "| stream | FAIL |" in proc.stdout


def test_full_mode_stream_warns_on_no_content() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={
            "FAKE_STREAM_BODY": 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        },
    )
    assert proc.returncode == 0
    assert "| stream | WARN |" in proc.stdout
    assert "Overall: WARN" in proc.stdout


def test_full_mode_provider_family_failure_isolated_per_family() -> None:
    """A single provider outage fails only that family's check, not the others."""
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_COMPLETION_CODE_CLAUDE_SONNET_4_6": "503"},
    )
    assert proc.returncode == 1
    assert "| provider_claude | FAIL | POST /v1/chat/completions (claude-sonnet-4-6) -> 503 |" in proc.stdout
    assert "| provider_gpt | PASS |" in proc.stdout
    assert "| provider_gemini | PASS |" in proc.stdout
    assert "Overall: FAIL" in proc.stdout


def test_full_mode_provider_models_env_override() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"DEEP_SMOKE_PROVIDER_MODELS": "onlyfamily=some-custom-model"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "| provider_onlyfamily | PASS |" in proc.stdout
    assert "provider_claude" not in proc.stdout
    assert "provider_gpt" not in proc.stdout
    assert "provider_gemini" not in proc.stdout


def test_full_mode_provider_models_invalid_entry_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"DEEP_SMOKE_PROVIDER_MODELS": "not-a-valid-pair"},
    )
    assert proc.returncode == 1
    assert "invalid DEEP_SMOKE_PROVIDER_MODELS entry" in proc.stdout


def test_full_mode_responses_and_messages_model_env_overrides(tmp_path) -> None:
    log_path = tmp_path / "curl.log"
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={
            "DEEP_SMOKE_RESPONSES_MODEL": "custom-responses-model",
            "DEEP_SMOKE_MESSAGES_MODEL": "custom-messages-model",
            "DEEP_SMOKE_STREAM_MODEL": "custom-stream-model",
            "FAKE_CURL_LOG": str(log_path),
        },
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    log_text = log_path.read_text()
    assert "custom-responses-model" in log_text
    assert "custom-messages-model" in log_text
    assert "custom-stream-model" in log_text


def test_full_mode_tags_requests_with_smoke_end_user(tmp_path) -> None:
    """Every --full request should carry the deep-smoke-<ts> tag somewhere in its body."""
    log_path = tmp_path / "curl.log"
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_CURL_LOG": str(log_path)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    tag_line = next(line for line in proc.stdout.splitlines() if line.startswith("## Deep Smoke Summary"))
    tag = tag_line.rsplit("tag=", 1)[-1].strip()
    assert tag.startswith("deep-smoke-")

    log_text = log_path.read_text()
    for path in ("/v1/chat/completions", "/v1/responses", "/v1/messages"):
        matching_lines = [line for line in log_text.splitlines() if path in line]
        assert matching_lines, f"no logged calls to {path}"
        assert all(tag in line for line in matching_lines), f"missing smoke tag in a call to {path}:\n{log_text}"


# ---------------------------------------------------------------------------
# --full mode: read-mostly admin checks (issue #400, bundle #396)
# ---------------------------------------------------------------------------


def test_full_mode_admin_status_http_failure_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_ADMIN_STATUS_CODE": "503"},
    )
    assert proc.returncode == 1
    assert "| admin_status | FAIL | GET /admin/status -> 503 |" in proc.stdout
    assert "Overall: FAIL" in proc.stdout


def test_full_mode_admin_status_error_body_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_ADMIN_STATUS_BODY": '{"error":"boom"}'},
    )
    assert proc.returncode == 1
    assert "| admin_status | FAIL |" in proc.stdout
    assert "boom" in proc.stdout


def test_full_mode_admin_credentials_http_failure_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_ADMIN_CREDENTIALS_CODE": "500"},
    )
    assert proc.returncode == 1
    assert "| admin_credentials | FAIL | GET /admin/credentials -> 500 |" in proc.stdout


def test_full_mode_admin_credentials_error_body_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_ADMIN_CREDENTIALS_BODY": '{"error":{"message":"unauthorized"}}'},
    )
    assert proc.returncode == 1
    assert "| admin_credentials | FAIL |" in proc.stdout
    assert "unauthorized" in proc.stdout


def test_full_mode_admin_quota_accepts_201() -> None:
    """Soft contract: any 2xx (not just 200) satisfies the quota check."""
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_ADMIN_QUOTA_CODE": "201"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "| admin_quota | PASS |" in proc.stdout


def test_full_mode_admin_quota_http_failure_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_ADMIN_QUOTA_CODE": "502"},
    )
    assert proc.returncode == 1
    assert "| admin_quota | FAIL | GET /admin/quota/status -> 502 |" in proc.stdout


def test_full_mode_admin_quota_non_json_body_fails() -> None:
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_ADMIN_QUOTA_BODY": "not json at all"},
    )
    assert proc.returncode == 1
    assert "| admin_quota | FAIL |" in proc.stdout
    assert "invalid JSON" in proc.stdout


def test_full_mode_admin_quota_soft_passes_on_minimal_body() -> None:
    """Soft contract: quota schema is still moving; a bare '{}' must pass."""
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_ADMIN_QUOTA_BODY": "{}"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "| admin_quota | PASS |" in proc.stdout


def test_full_mode_admin_quota_soft_passes_even_with_unexpected_status() -> None:
    """Soft contract: an unexpected top-level 'status' value never fails the check."""
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_ADMIN_QUOTA_BODY": '{"status":"degraded","accounts":"not-a-list"}'},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "| admin_quota | PASS |" in proc.stdout


def test_full_mode_admin_checks_forward_admin_key_header(tmp_path) -> None:
    log_path = tmp_path / "curl.log"
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_CURL_LOG": str(log_path), "DEEP_SMOKE_ADMIN_KEY": "test-admin-key-123"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    log_text = log_path.read_text()
    for path in ("/admin/status", "/admin/credentials", "/admin/quota/status"):
        matching_lines = [line for line in log_text.splitlines() if path in line]
        assert matching_lines, f"no logged calls to {path}"
        assert all("test-admin-key-123" in line for line in matching_lines), (
            f"missing x-admin-key forwarding for {path}:\n{log_text}"
        )

    # Non-admin routes must NOT receive the admin key.
    non_admin_lines = [line for line in log_text.splitlines() if "/v1/chat/completions" in line]
    assert non_admin_lines
    assert all("test-admin-key-123" not in line for line in non_admin_lines)


def test_full_mode_admin_checks_omit_header_when_admin_key_unset(tmp_path) -> None:
    log_path = tmp_path / "curl.log"
    proc = _run_deep_smoke(
        ["--env", "staging", "--full"],
        env_overrides={"FAKE_CURL_LOG": str(log_path)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    log_text = log_path.read_text()
    admin_status_lines = [line for line in log_text.splitlines() if "/admin/status" in line]
    assert admin_status_lines
    # Log format is "<url> <payload> <admin_key_header>"; header field should be empty.
    assert all(line.split(" ")[-1] == "" for line in admin_status_lines)
