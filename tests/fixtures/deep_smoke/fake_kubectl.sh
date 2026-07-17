#!/usr/bin/env bash
# Fake kubectl for offline tests/test_deep_smoke.py runs.
#
# deep-smoke.sh calls kubectl in four shapes, routed here by scanning the
# argument list (order-independent, since --context/-n placement varies):
#   1. `... get pods -o json`                                  -> pods check
#   2. `... get jobs -o json`                                  -> jobs check (issue #401)
#   3. `... get pods -l <selector> -o jsonpath=...`             -> Postgres pod lookup (issue #401)
#   4. `... exec <pod> -c <container> -- psql ...`              -> SpendLogs query (issue #401)
#
# All responses/exit codes are controlled via env vars so tests can drive
# every scenario without touching the network or a real cluster. Set
# FAKE_KUBECTL_LOG=/path/to/file to append the full argument list for every
# call (space-joined) — used by tests asserting the SpendLogs query/pod
# lookup used the expected namespace, selector, or smoke tag.
set -uo pipefail

exit_code="${FAKE_KUBECTL_EXIT:-0}"
if [ "$exit_code" != "0" ]; then
  echo "${FAKE_KUBECTL_STDERR:-fake kubectl error}" >&2
  exit "$exit_code"
fi

if [ -n "${FAKE_KUBECTL_LOG:-}" ]; then
  # Never log onto stdout/stderr — that would prepend argv to the JSON payload
  # and break check-pods / check-jobs parsers ("Extra data" / invalid JSON).
  case "$FAKE_KUBECTL_LOG" in
    /dev/stdout|/dev/stderr|-|/dev/fd/1|/dev/fd/2)
      echo "FAKE_KUBECTL_LOG must be a real file path, not $FAKE_KUBECTL_LOG" >&2
      exit 2
      ;;
  esac
  printf '%s\n' "$*" >>"$FAKE_KUBECTL_LOG"
fi

contains() {
  local needle="$1"
  shift
  for arg in "$@"; do
    [ "$arg" = "$needle" ] && return 0
  done
  return 1
}

has_prefix_arg() {
  local prefix="$1"
  shift
  for arg in "$@"; do
    case "$arg" in
      "$prefix"*) return 0 ;;
    esac
  done
  return 1
}

if contains "exec" "$@"; then
  exit_code="${FAKE_PSQL_EXIT:-0}"
  if [ "$exit_code" != "0" ]; then
    echo "${FAKE_PSQL_STDERR:-fake psql error}" >&2
    exit "$exit_code"
  fi
  if [ -n "${FAKE_SPENDLOGS_JSON+set}" ]; then
    # Explicit override (may be "[]" to simulate zero matching rows).
    printf '%s' "$FAKE_SPENDLOGS_JSON"
  else
    # Default: a row matching the fixed default completion id
    # ("chatcmpl-fake-000", see fake_curl.sh) with a fresh "startTime" so it
    # always falls inside the matcher's recency window. This keeps unrelated
    # full-mode tests (that don't care about SpendLogs) green by default.
    now_ts=$(date -u +%Y-%m-%dT%H:%M:%S)
    printf '[{"request_id":"chatcmpl-fake-000","end_user":"unused-default-fixture-row","startTime":"%s"}]' "$now_ts"
  fi
  exit 0
fi

if contains "jobs" "$@"; then
  exit_code="${FAKE_KUBECTL_JOBS_EXIT:-0}"
  if [ "$exit_code" != "0" ]; then
    echo "${FAKE_KUBECTL_JOBS_STDERR:-fake kubectl jobs error}" >&2
    exit "$exit_code"
  fi
  jobs_json="${FAKE_JOBS_JSON-}"
  if [ -z "$jobs_json" ]; then
    jobs_json='{"items":[]}'
  fi
  printf '%s' "$jobs_json"
  exit 0
fi

if contains "pods" "$@" && has_prefix_arg "jsonpath=" "$@"; then
  exit_code="${FAKE_PG_POD_LOOKUP_EXIT:-0}"
  if [ "$exit_code" != "0" ]; then
    echo "${FAKE_PG_POD_LOOKUP_STDERR:-fake kubectl pod-lookup error}" >&2
    exit "$exit_code"
  fi
  printf '%s' "${FAKE_PG_POD_NAME-postgres-0}"
  exit 0
fi

if contains "pods" "$@"; then
  pods_json="${FAKE_PODS_JSON-}"
  if [ -z "$pods_json" ]; then
    pods_json='{"items":[]}'
  fi
  printf '%s' "$pods_json"
  exit 0
fi

# Unmatched argv shape — still emit valid empty list JSON (never fall through
# without exiting; a missing exit here previously concatenated payloads and
# caused "invalid JSON: Extra data" in check-pods).
printf '%s' '{"items":[]}'
exit 0
