#!/usr/bin/env bash
# Regression tests: sync-models must preserve catalog entries on 429/cooldown probes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLASSIFY="$SCRIPT_DIR/scripts/sync_models_probe_classify.py"

PASS=0
FAIL=0

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }

probe_exit_for_http() {
  local http_code="$1"
  local body="$2"
  PYTHONPATH="$SCRIPT_DIR/scripts" python3 - "$http_code" "$body" <<'PY'
import sys
from sync_models_probe_classify import classify_probe_response, probe_exit_code
http_code, body = sys.argv[1], sys.argv[2]
print(probe_exit_code(classify_probe_response(http_code, body)))
PY
}

should_remove() {
  local exit_code="$1"
  PYTHONPATH="$SCRIPT_DIR/scripts" python3 - "$exit_code" <<'PY'
import sys
from sync_models_probe_classify import should_remove_model_from_config
print("yes" if should_remove_model_from_config(int(sys.argv[1])) else "no")
PY
}

echo "── sync-models probe classification (shell) ──"

# 429 quota cooldown — must preserve catalog
exit_429=$(probe_exit_for_http "429" '{"error":{"message":"rate limit exceeded"}}')
if [[ "$exit_429" == "42" ]] && [[ "$(should_remove "$exit_429")" == "no" ]]; then
  pass "429 maps to preserve exit (42), not removal"
else
  fail "429 should map to exit 42 without removal (got exit=$exit_429 remove=$(should_remove "$exit_429"))"
fi

# 401 auth failure — preserve (do not treat as dead model)
exit_401=$(probe_exit_for_http "401" '{"error":{"message":"invalid api key"}}')
if [[ "$exit_401" == "42" ]] && [[ "$(should_remove "$exit_401")" == "no" ]]; then
  pass "401 maps to preserve exit (42), not removal"
else
  fail "401 should preserve model (got exit=$exit_401 remove=$(should_remove "$exit_401"))"
fi

# 404 missing model — safe to remove
exit_404=$(probe_exit_for_http "404" '{"error":{"message":"model not found"}}')
if [[ "$exit_404" == "44" ]] && [[ "$(should_remove "$exit_404")" == "yes" ]]; then
  pass "404 maps to removal exit (44)"
else
  fail "404 should map to exit 44 for removal (got exit=$exit_404 remove=$(should_remove "$exit_404"))"
fi

# Body-only quota signal on HTTP 400 — still transient
exit_quota=$(probe_exit_for_http "400" '{"error":{"message":"quota exceeded for model"}}')
if [[ "$exit_quota" == "42" ]] && [[ "$(should_remove "$exit_quota")" == "no" ]]; then
  pass "quota message on HTTP 400 preserves catalog"
else
  fail "quota body on 400 should preserve (got exit=$exit_quota)"
fi

echo ""
if [[ "$FAIL" -eq 0 ]]; then
  echo "All $PASS sync-models probe regression checks passed."
  exit 0
fi

echo "$FAIL check(s) failed, $PASS passed."
exit 1
