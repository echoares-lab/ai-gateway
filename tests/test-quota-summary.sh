#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT
mkdir -p "$TMP_DIR/bin" "$TMP_DIR/home"
cp "$REPO_DIR/cliproxy-setup.sh" "$TMP_DIR/cliproxy-setup.sh"

cat >"$TMP_DIR/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$FAKE_CURL_ARGS"
case "$FAKE_CURL_SCENARIO" in
  accounts)
    cat <<'JSON'
{"status":"ok","accounts":[{"email":"operator@example.com","provider":"claude","provider_label":"Claude","plan_type":"max","account_status":"active","quota":{"windows":{"five_hour":{"utilization_pct":10.0,"resets_at":"2026-07-11T15:00:00Z"},"seven_day":{"utilization_pct":20.0,"resets_at":"2026-07-18T10:00:00Z"},"binding":{"utilization_pct":45.0,"resets_at":"2026-07-11T12:00:00Z","resets_in":"2h30m"}}}}]}
JSON
    ;;
  empty) printf '%s\n' '{"status":"ok","accounts":[]}' ;;
  failure) exit 22 ;;
esac
EOF
chmod +x "$TMP_DIR/bin/curl"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }
contains() { [[ "$1" == *"$2"* ]]; }

run_summary() {
  local scenario="$1" url="$2" key="${3:-}"
  FAKE_CURL_SCENARIO="$scenario" \
  FAKE_CURL_ARGS="$TMP_DIR/curl-args" \
  GATEWAY_ENGINE_URL="$url" \
  GATEWAY_ENGINE_ADMIN_KEY="$key" \
  HOME="$TMP_DIR/home" \
  PATH="$TMP_DIR/bin:$PATH" \
    bash "$TMP_DIR/cliproxy-setup.sh" quota-summary 2>&1
}

echo "── quota-summary helper ──"

output=$(run_summary accounts "https://gateway.example.test/") || true
args=$(cat "$TMP_DIR/curl-args")
if contains "$args" "https://gateway.example.test/admin/quota/status" && \
   ! contains "$args" "x-admin-key"; then
  pass "uses the selected Gateway Engine URL without an empty admin header"
else
  fail "expected Gateway Engine quota URL and no admin header (args: $args)"
fi

if contains "$output" "[Claude]" && contains "$output" "operator@example.com" && \
   contains "$output" "active" && contains "$output" "max" && \
   contains "$output" "five_hour" && contains "$output" "10.0%" && \
   contains "$output" "seven_day" && contains "$output" "20.0%" && \
   contains "$output" "binding" && contains "$output" "45.0%" && \
   contains "$output" "2h30m"; then
  pass "renders account details and five-hour, seven-day, and binding windows"
else
  fail "expected rendered account quota windows (output: $output)"
fi

secret="admin-secret-that-must-not-print"
output=$(run_summary empty "http://localhost:4010" "$secret") || true
args=$(cat "$TMP_DIR/curl-args")
if contains "$args" "x-admin-key: $secret" && ! contains "$output" "$secret"; then
  pass "conditionally sends the admin key without printing it"
else
  fail "expected a private x-admin-key header (args: $args; output: $output)"
fi

if contains "$output" "no accounts found"; then
  pass "handles an empty account list"
else
  fail "expected an empty-account explanation (output: $output)"
fi

set +e
output=$(run_summary failure "https://gateway.example.test")
status=$?
set -e
if [[ "$status" -ne 0 ]] && contains "$output" "ERROR:" && \
   contains "$output" "Gateway Engine"; then
  pass "reports Gateway Engine HTTP failures and exits nonzero"
else
  fail "expected a nonzero Gateway Engine failure (status=$status; output: $output)"
fi

echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "All $PASS quota-summary regression checks passed."
  exit 0
fi
echo "$FAIL check(s) failed, $PASS passed."
exit 1
