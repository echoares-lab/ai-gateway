#!/usr/bin/env python3
"""JSON/response assertion helper for scripts/ops/deep-smoke.sh.

deep-smoke.sh shells out to this helper (stdin -> JSON payload, exit code ->
pass/fail/warn) so the response-shape assertions live in testable Python
instead of fragile pure-bash JSON parsing. See
docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md.

Exit code convention for every ``check-*`` subcommand:
    0 = pass, 1 = fail, 2 = warn (soft — non-fatal unless the caller runs
    with ``--strict``).

The ``--quick`` checks (health/ready/version/models/completion/pods) and the
``--full`` API-shape/streaming/provider-family checks (chat completions,
Responses API, Claude Messages API, one SSE stream, claude/gpt/gemini
allowlist) are implemented here. Soft admin/quota, SpendLogs, cluster Jobs,
and Langfuse checks remain out of scope for this issue (bundle #396, issues
#400-#401).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

REQUIRED_VERSION_KEYS = ("version", "git_sha", "display_version")

_EXIT_CODES = {"pass": 0, "fail": 1, "warn": 2}


@dataclass(frozen=True)
class CheckOutcome:
    status: str  # "pass" | "fail" | "warn"
    message: str

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self.status]


def parse_json(text: str) -> tuple[object | None, str | None]:
    """Parse `text` as JSON. Returns (payload, None) or (None, error_message)."""
    stripped = (text or "").strip()
    if not stripped:
        return None, "empty response body"
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


def check_version_payload(payload: object) -> CheckOutcome:
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from GET /version")
    missing = [key for key in REQUIRED_VERSION_KEYS if key not in payload]
    if missing:
        return CheckOutcome("fail", f"/version missing keys: {', '.join(missing)}")
    return CheckOutcome(
        "pass",
        f"version={payload.get('version')} git_sha={payload.get('git_sha')}",
    )


def check_models_payload(payload: object) -> CheckOutcome:
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from GET /v1/models")
    data = payload.get("data")
    if not isinstance(data, list):
        return CheckOutcome("fail", "/v1/models response missing a 'data' array")
    if len(data) == 0:
        return CheckOutcome("fail", "/v1/models returned zero models")
    return CheckOutcome("pass", f"{len(data)} model(s) available")


def check_completion_payload(payload: object) -> CheckOutcome:
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from POST /v1/chat/completions")
    if "error" in payload:
        err = payload.get("error")
        detail = err.get("message") if isinstance(err, dict) else err
        return CheckOutcome("fail", f"completion returned an error: {detail}")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return CheckOutcome("fail", "completion response has no choices")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    text = first.get("text") if isinstance(first, dict) else None
    if not content and not text:
        return CheckOutcome("warn", "completion succeeded but returned empty content")
    return CheckOutcome("pass", "completion returned non-empty content")


def check_responses_payload(payload: object) -> CheckOutcome:
    """Validate a POST /v1/responses body (OpenAI Responses API shape)."""
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from POST /v1/responses")
    if "error" in payload:
        err = payload.get("error")
        detail = err.get("message") if isinstance(err, dict) else err
        return CheckOutcome("fail", f"/v1/responses returned an error: {detail}")
    output = payload.get("output")
    if not isinstance(output, list) or not output:
        return CheckOutcome("fail", "/v1/responses response missing a non-empty 'output' array")
    status = payload.get("status")
    has_text = False
    for item in output:
        if not isinstance(item, dict):
            continue
        for block in item.get("content", []) or []:
            if isinstance(block, dict) and block.get("text"):
                has_text = True
    if not has_text:
        return CheckOutcome("warn", f"/v1/responses succeeded (status={status}) but returned empty output text")
    return CheckOutcome("pass", f"/v1/responses status={status} output item(s)={len(output)}")


def check_messages_payload(payload: object) -> CheckOutcome:
    """Validate a POST /v1/messages body (Anthropic Claude Messages API shape)."""
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from POST /v1/messages")
    if payload.get("type") == "error":
        err = payload.get("error")
        detail = err.get("message") if isinstance(err, dict) else err
        return CheckOutcome("fail", f"/v1/messages returned an error: {detail}")
    content = payload.get("content")
    if not isinstance(content, list) or not content:
        return CheckOutcome("fail", "/v1/messages response missing a non-empty 'content' array")
    text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
    if not text_blocks:
        return CheckOutcome("warn", "/v1/messages succeeded but returned no non-empty text content blocks")
    return CheckOutcome(
        "pass",
        f"/v1/messages stop_reason={payload.get('stop_reason')} content block(s)={len(content)}",
    )


def check_stream_payload(text: str) -> CheckOutcome:
    """Validate a raw SSE body from a streaming POST /v1/chat/completions call.

    Expects OpenAI-style ``data: {...}`` chunks, optionally terminated by a
    ``data: [DONE]`` sentinel. Passes when at least one chunk is observed and
    the stream reaches a clean finish (``[DONE]`` and/or a terminal
    ``finish_reason``); fails on an empty/unparseable stream or one that cuts
    off without any finish signal; warns if the stream finished cleanly but no
    chunk carried any delta content (e.g. an all-metadata stream).
    """
    if not text or not text.strip():
        return CheckOutcome("fail", "empty SSE stream body")

    data_lines = [line[len("data: ") :] for line in text.splitlines() if line.startswith("data: ")]
    if not data_lines:
        return CheckOutcome("fail", "no 'data:' lines found in SSE stream body")

    saw_done = False
    saw_finish_reason = False
    saw_content = False
    chunk_count = 0
    last_error: str | None = None

    for raw in data_lines:
        raw = raw.strip()
        if raw == "[DONE]":
            saw_done = True
            continue
        try:
            chunk = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(chunk, dict) and isinstance(chunk.get("error"), (dict, str)):
            err = chunk["error"]
            last_error = err.get("message") if isinstance(err, dict) else err
            continue
        chunk_count += 1
        choices = chunk.get("choices") if isinstance(chunk, dict) else None
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                delta = first.get("delta")
                if isinstance(delta, dict) and delta.get("content"):
                    saw_content = True
                if first.get("finish_reason"):
                    saw_finish_reason = True

    if last_error and chunk_count == 0:
        return CheckOutcome("fail", f"SSE stream returned an error: {last_error}")
    if chunk_count == 0:
        return CheckOutcome("fail", "SSE stream had no parseable JSON data chunks")
    if not saw_done and not saw_finish_reason:
        return CheckOutcome(
            "fail",
            f"SSE stream ended without [DONE] or a finish_reason ({chunk_count} chunk(s) seen)",
        )
    if not saw_content:
        return CheckOutcome(
            "warn",
            f"SSE stream finished cleanly but no delta content observed ({chunk_count} chunk(s))",
        )
    return CheckOutcome("pass", f"{chunk_count} data chunk(s), finish_reason seen, stream closed cleanly")


def _pod_ready_detail(pod: object) -> tuple[bool, str]:
    if not isinstance(pod, dict):
        return False, "<malformed pod entry>"
    name = pod.get("metadata", {}).get("name", "<unknown>") if isinstance(pod.get("metadata"), dict) else "<unknown>"
    status = pod.get("status", {}) if isinstance(pod.get("status"), dict) else {}
    phase = status.get("phase")
    if phase == "Succeeded":
        return True, f"{name}: Succeeded (completed Job, ok)"
    conditions = status.get("conditions") or []
    ready_condition = next(
        (c for c in conditions if isinstance(c, dict) and c.get("type") == "Ready"),
        None,
    )
    if ready_condition is not None and ready_condition.get("status") == "True":
        return True, f"{name}: Ready"
    ready_status = ready_condition.get("status") if ready_condition else "unknown"
    return False, f"{name}: phase={phase} ready={ready_status}"


def check_pods_payload(payload: object, allowlist: list[str] | None = None) -> CheckOutcome:
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from 'kubectl get pods -o json'")
    items = payload.get("items")
    if not isinstance(items, list):
        return CheckOutcome("fail", "kubectl pods response missing an 'items' array")
    if not items:
        return CheckOutcome("warn", "no pods found in namespace")

    allowlist = [token for token in (allowlist or []) if token]
    skipped = 0
    not_ready: list[str] = []
    for pod in items:
        name = pod.get("metadata", {}).get("name", "") if isinstance(pod, dict) else ""
        if any(token in name for token in allowlist):
            skipped += 1
            continue
        ok, detail = _pod_ready_detail(pod)
        if not ok:
            not_ready.append(detail)

    if not_ready:
        return CheckOutcome(
            "fail",
            f"{len(not_ready)} pod(s) not ready: " + "; ".join(not_ready),
        )
    checked = len(items) - skipped
    suffix = f" ({skipped} allowlisted skipped)" if skipped else ""
    return CheckOutcome("pass", f"{checked} pod(s) checked, all ready{suffix}")


def _read_stdin_json() -> tuple[object | None, str | None]:
    return parse_json(sys.stdin.read())


def _emit(outcome: CheckOutcome) -> int:
    print(outcome.message)
    return outcome.exit_code


def cli_check_version() -> int:
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_version_payload(payload))


def cli_check_models() -> int:
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_models_payload(payload))


def cli_check_completion() -> int:
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_completion_payload(payload))


def cli_check_responses() -> int:
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_responses_payload(payload))


def cli_check_messages() -> int:
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_messages_payload(payload))


def cli_check_stream() -> int:
    return _emit(check_stream_payload(sys.stdin.read()))


def cli_check_pods(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="deep_smoke.py check-pods")
    parser.add_argument(
        "--allowlist",
        default="",
        help="comma-separated pod-name substrings to skip readiness checks for",
    )
    args = parser.parse_args(argv)
    allowlist = [tok.strip() for tok in args.allowlist.split(",") if tok.strip()]
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_pods_payload(payload, allowlist))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if not args:
        print(
            "usage: deep_smoke.py <check-version|check-models|check-completion|"
            "check-responses|check-messages|check-stream|check-pods> [options]",
            file=sys.stderr,
        )
        return 2

    cmd, rest = args[0], args[1:]
    if cmd == "check-version":
        return cli_check_version()
    if cmd == "check-models":
        return cli_check_models()
    if cmd == "check-completion":
        return cli_check_completion()
    if cmd == "check-responses":
        return cli_check_responses()
    if cmd == "check-messages":
        return cli_check_messages()
    if cmd == "check-stream":
        return cli_check_stream()
    if cmd == "check-pods":
        return cli_check_pods(rest)

    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
