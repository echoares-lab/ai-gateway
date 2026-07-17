#!/usr/bin/env python3
"""JSON/response assertion helper for scripts/ops/deep-smoke.sh.

deep-smoke.sh shells out to this helper (stdin -> JSON payload, exit code ->
pass/fail/warn) so the response-shape assertions live in testable Python
instead of fragile pure-bash JSON parsing. See
docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md.

Exit code convention for every ``check-*`` subcommand:
    0 = pass, 1 = fail, 2 = warn (soft — non-fatal unless the caller runs
    with ``--strict``).

The ``--quick`` checks (health/ready/version/models/completion/pods), the
``--full`` API-shape/streaming/provider-family checks (chat completions,
Responses API, Claude Messages API, one SSE stream, claude/gpt/gemini
allowlist), the ``--full`` read-mostly admin checks (``/admin/status``,
``/admin/credentials``, soft ``/admin/quota/status``), the ``--full``
cluster Job check (bootstrap/migration Jobs not ``Failed`` when present),
and the ``--full`` ``LiteLLM_SpendLogs`` DB side-effect check are
implemented here (bundle #396; Jobs/SpendLogs are issue #401). Langfuse
checks remain out of scope for this issue.

**SpendLogs matching** (issue #401): after a tagged completion, deep-smoke.sh
polls ``public."LiteLLM_SpendLogs"`` (see db/seed-litellm-mock.sql) via
``kubectl exec`` into the Postgres pod + ``psql`` for a row matching the
smoke ``end_user`` and/or ``request_id`` within a short recency window.
Matching on *either* identifier is sufficient (either can be missing/blank
depending on what the API surface under test forwards — see the
``metadata.user`` / ``metadata.user_id`` notes in deep-smoke.sh), but a
match older than the window never counts, to avoid false positives from
stale rows that happen to share a smoke tag from a previous run.

**Soft quota contract** (issue #400): ``GET /admin/quota/status`` is only
asserted to return an HTTP 2xx status with a JSON object body. The quota
schema is still moving (see docs/API_DOCUMENTATION.md and the quota-alert
work in progress), so no field contracts are enforced here — not
``status``, ``accounts`` shape, per-window breakdowns, ``live_status``, nor
Apprise/alert-tier fields. ``check_admin_quota_payload`` only *notes*
whether the optional soft extras (top-level ``status`` in ``("ok",)`` and
an ``accounts`` list) look as expected; it never fails or warns on them.
Follow-up issue #403 will replace this with schema-validated asserts once
the quota OpenAPI schema is frozen.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

REQUIRED_VERSION_KEYS = ("version", "git_sha", "display_version")
DEFAULT_SPENDLOGS_WINDOW_MINUTES = 15

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


def check_jobs_payload(payload: object, allowlist: list[str] | None = None) -> CheckOutcome:
    """Validate a 'kubectl get jobs -o json' body (issue #401, bundle #396).

    Pods-Ready is already covered by ``check_pods_payload`` in ``--quick``
    (a completed Job's pod shows ``phase: Succeeded``, which that check
    already treats as ok). This check adds the Job-specific assertion the
    design calls for: any bootstrap/migration Jobs *present* (e.g. a
    Postgres bootstrap PreSync hook, ``litellm-migrate``, ``gateway-migrate``
    — see docs/CICD_PHASE2_STAGING.md) must not be in a ``Failed`` state.

    Jobs are often one-shot and may already be pruned by the time an
    operator runs deep-smoke, so *no* Jobs present is not a failure. A Job
    that is still ``Active``/running (not yet ``Complete`` or ``Failed``) is
    also not a failure — only an explicit ``Failed`` condition trips this
    check.
    """
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from 'kubectl get jobs -o json'")
    items = payload.get("items")
    if not isinstance(items, list):
        return CheckOutcome("fail", "kubectl jobs response missing an 'items' array")
    if not items:
        return CheckOutcome("pass", "no bootstrap/migration Jobs found in namespace (ok)")

    allowlist = [token for token in (allowlist or []) if token]
    skipped = 0
    checked = 0
    failed: list[str] = []
    for job in items:
        name = job.get("metadata", {}).get("name", "<unknown>") if isinstance(job, dict) else "<unknown>"
        if any(token in name for token in allowlist):
            skipped += 1
            continue
        checked += 1
        status = job.get("status", {}) if isinstance(job, dict) else {}
        conditions = status.get("conditions") or []
        failed_condition = next(
            (c for c in conditions if isinstance(c, dict) and c.get("type") == "Failed" and c.get("status") == "True"),
            None,
        )
        if failed_condition is not None:
            reason = failed_condition.get("reason", "Failed")
            failed.append(f"{name}: {reason}")

    if failed:
        return CheckOutcome("fail", f"{len(failed)} Job(s) failed: " + "; ".join(failed))
    suffix = f" ({skipped} allowlisted skipped)" if skipped else ""
    return CheckOutcome("pass", f"{checked} Job(s) checked, none failed{suffix}")


def _parse_spend_log_timestamp(value: object) -> datetime | None:
    """Parse a LiteLLM_SpendLogs "startTime" value into an aware UTC datetime.

    psql (with ``-t -A`` / ``row_to_json``) renders Postgres
    ``timestamp without time zone`` values as naive ISO-ish strings (e.g.
    ``"2026-07-17T14:20:00.123"`` or ``"2026-07-17 14:20:00.123"``). The
    column has no timezone, but the smoke tooling and the cluster both run
    in UTC, so a naive value is treated as UTC.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if "T" not in text and " " in text:
        text = text.replace(" ", "T", 1)
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def find_matching_spend_log_row(
    rows: list[object],
    end_user: str | None,
    request_id: str | None,
    window_minutes: int = DEFAULT_SPENDLOGS_WINDOW_MINUTES,
    now: datetime | None = None,
) -> dict | None:
    """Return the most recent row matching `end_user` and/or `request_id`.

    A row matches if its ``end_user`` equals `end_user` OR its
    ``request_id`` equals `request_id` (either identifier is sufficient —
    see the module docstring). A match is only counted if its ``startTime``
    falls within the trailing `window_minutes` of `now` (defaults to the
    current UTC time); rows with an unparseable/missing ``startTime`` never
    match, since recency is what makes this a meaningful DB *side effect*
    check rather than a coincidental identifier collision.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)
    best: tuple[datetime, dict] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        matches_request_id = bool(request_id) and row.get("request_id") == request_id
        matches_end_user = bool(end_user) and row.get("end_user") == end_user
        if not (matches_request_id or matches_end_user):
            continue
        ts = _parse_spend_log_timestamp(row.get("startTime"))
        if ts is None or ts < cutoff:
            continue
        if best is None or ts > best[0]:
            best = (ts, row)
    return best[1] if best else None


def check_spendlogs_payload(
    payload: object,
    end_user: str | None,
    request_id: str | None,
    window_minutes: int = DEFAULT_SPENDLOGS_WINDOW_MINUTES,
    now: datetime | None = None,
) -> CheckOutcome:
    """Match a recent LiteLLM_SpendLogs row against the smoke tag (issue #401).

    `payload` is the JSON array produced by deep-smoke.sh's psql query
    (``SELECT request_id, end_user, "startTime" FROM
    public."LiteLLM_SpendLogs" WHERE end_user = <tag> OR request_id = <id>
    ORDER BY "startTime" DESC LIMIT 20``). This is the DB *side effect*
    check (bundle #396 check inventory item 13): it proves a tagged smoke
    request actually reached LiteLLM and was logged, not just that the HTTP
    call returned 200.
    """
    if not end_user and not request_id:
        return CheckOutcome("fail", "check-spendlogs requires --end-user and/or --request-id")
    if not isinstance(payload, list):
        return CheckOutcome("fail", "expected a JSON array of LiteLLM_SpendLogs rows")

    match = find_matching_spend_log_row(payload, end_user, request_id, window_minutes, now)
    if match is None:
        if not payload:
            return CheckOutcome(
                "fail",
                f"no LiteLLM_SpendLogs row found for end_user={end_user!r} request_id={request_id!r} "
                f"within {window_minutes}m (query returned 0 rows)",
            )
        return CheckOutcome(
            "fail",
            f"no LiteLLM_SpendLogs row matched end_user={end_user!r} request_id={request_id!r} "
            f"within {window_minutes}m ({len(payload)} row(s) returned, none matched/recent enough)",
        )
    return CheckOutcome(
        "pass",
        f"LiteLLM_SpendLogs row found: request_id={match.get('request_id')!r} "
        f"end_user={match.get('end_user')!r} startTime={match.get('startTime')!r}",
    )


def check_admin_status_payload(payload: object) -> CheckOutcome:
    """Validate a GET /admin/status body — read-mostly, 2xx + JSON object.

    Deliberately shallow: does not assert the ``panels``/``schema_version``
    shape, only that the body is a JSON object and does not carry a
    top-level ``error`` key.
    """
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from GET /admin/status")
    if payload.get("error"):
        return CheckOutcome("fail", f"/admin/status returned an error: {payload.get('error')}")
    schema_version = payload.get("schema_version", "unknown")
    return CheckOutcome("pass", f"/admin/status ok (schema_version={schema_version})")


def check_admin_credentials_payload(payload: object) -> CheckOutcome:
    """Validate a GET /admin/credentials body — non-error, JSON object.

    Soft: only checks for a top-level ``error`` key and, when present,
    that ``credentials`` is a list. Does not assert per-record fields.
    """
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from GET /admin/credentials")
    if "error" in payload:
        err = payload.get("error")
        detail = err.get("message") if isinstance(err, dict) else err
        return CheckOutcome("fail", f"/admin/credentials returned an error: {detail}")
    credentials = payload.get("credentials")
    if credentials is not None and not isinstance(credentials, list):
        return CheckOutcome("fail", "/admin/credentials 'credentials' field is present but not a list")
    count = len(credentials) if isinstance(credentials, list) else 0
    return CheckOutcome("pass", f"/admin/credentials ok ({count} credential(s))")


def check_admin_quota_payload(payload: object) -> CheckOutcome:
    """Soft GET /admin/quota/status check (issue #400) — 2xx + JSON object ONLY.

    The quota response schema is still moving (bundle #396; hardening is
    tracked separately as issue #403), so this deliberately does not assert
    field contracts for windows, live_status, Apprise, or alert tiers. The
    caller is responsible for the "2xx" half of the contract (this function
    only ever sees bodies the shell wrapper already decided were behind a
    2xx status code); this function's job is just "is it a JSON object".

    When the optional soft extras from the design doc are present (top-level
    ``status`` and ``accounts``), a short note about whether they look sane
    is appended to the message — but this is purely informational and never
    changes the pass/fail/warn outcome.
    """
    if not isinstance(payload, dict):
        return CheckOutcome("fail", "expected a JSON object from GET /admin/quota/status")

    notes: list[str] = []
    status = payload.get("status")
    if status is not None and status != "ok":
        notes.append(f"status={status!r} (soft, not asserted)")
    accounts = payload.get("accounts")
    if accounts is not None and not isinstance(accounts, list):
        notes.append("'accounts' present but not a list (soft, not asserted)")
    elif isinstance(accounts, list):
        notes.append(f"{len(accounts)} account(s)")

    detail = "/admin/quota/status ok (2xx, JSON object; soft contract only)"
    if notes:
        detail += " — " + "; ".join(notes)
    return CheckOutcome("pass", detail)


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


def cli_check_admin_status() -> int:
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_admin_status_payload(payload))


def cli_check_admin_credentials() -> int:
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_admin_credentials_payload(payload))


def cli_check_admin_quota() -> int:
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_admin_quota_payload(payload))


def cli_check_jobs(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="deep_smoke.py check-jobs")
    parser.add_argument(
        "--allowlist",
        default="",
        help="comma-separated Job-name substrings to skip Failed-condition checks for",
    )
    args = parser.parse_args(argv)
    allowlist = [tok.strip() for tok in args.allowlist.split(",") if tok.strip()]
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(check_jobs_payload(payload, allowlist))


def cli_check_spendlogs(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="deep_smoke.py check-spendlogs")
    parser.add_argument("--end-user", default="", help="smoke end_user tag to match")
    parser.add_argument("--request-id", default="", help="completion response id to match")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=DEFAULT_SPENDLOGS_WINDOW_MINUTES,
        help="only rows within this many trailing minutes count as a match",
    )
    args = parser.parse_args(argv)
    payload, err = _read_stdin_json()
    if err:
        return _emit(CheckOutcome("fail", err))
    return _emit(
        check_spendlogs_payload(
            payload,
            end_user=args.end_user or None,
            request_id=args.request_id or None,
            window_minutes=args.window_minutes,
        )
    )


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
            "check-responses|check-messages|check-stream|check-pods|"
            "check-admin-status|check-admin-credentials|check-admin-quota|"
            "check-jobs|check-spendlogs> [options]",
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
    if cmd == "check-admin-status":
        return cli_check_admin_status()
    if cmd == "check-admin-credentials":
        return cli_check_admin_credentials()
    if cmd == "check-admin-quota":
        return cli_check_admin_quota()
    if cmd == "check-jobs":
        return cli_check_jobs(rest)
    if cmd == "check-spendlogs":
        return cli_check_spendlogs(rest)

    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
