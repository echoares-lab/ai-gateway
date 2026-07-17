#!/usr/bin/env python3
"""JSON/response assertion helper for scripts/ops/deep-smoke.sh.

deep-smoke.sh shells out to this helper (stdin -> JSON payload, exit code ->
pass/fail/warn) so the response-shape assertions live in testable Python
instead of fragile pure-bash JSON parsing. See
docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md.

Exit code convention for every ``check-*`` subcommand:
    0 = pass, 1 = fail, 2 = warn (soft — non-fatal unless the caller runs
    with ``--strict``).

Only the ``--quick`` checks (health/ready/version/models/completion/pods)
are implemented here; ``--full`` checks (API shapes, streaming, SpendLogs,
Langfuse, quota) are out of scope for this issue (bundle #396, issues
#399-#401).
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
            "usage: deep_smoke.py <check-version|check-models|check-completion|check-pods> [options]",
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
    if cmd == "check-pods":
        return cli_check_pods(rest)

    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
