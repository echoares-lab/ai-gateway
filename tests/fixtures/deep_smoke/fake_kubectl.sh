#!/usr/bin/env bash
# Fake kubectl for offline tests/test_deep_smoke.py runs.
#
# deep-smoke.sh calls `kubectl [--context ...] -n <ns> get pods -o json`.
# This fake ignores the arguments (beyond simulating failure) and returns a
# canned pods payload / exit code controlled via env vars.
set -euo pipefail

exit_code="${FAKE_KUBECTL_EXIT:-0}"
if [ "$exit_code" != "0" ]; then
  echo "${FAKE_KUBECTL_STDERR:-fake kubectl error}" >&2
  exit "$exit_code"
fi

pods_json="${FAKE_PODS_JSON-}"
if [ -z "$pods_json" ]; then
  pods_json='{"items":[]}'
fi

printf '%s' "$pods_json"
