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
: >"$FAKE_CURL_STDIN"
for arg in "$@"; do
  if [[ "$arg" == "@-" ]]; then
    cat >"$FAKE_CURL_STDIN"
    break
  fi
done
case "$FAKE_CURL_SCENARIO" in
  accounts)
    cat <<'JSON'
{"status":"ok","accounts":[{"email":"operator@example.com","provider":"claude","provider_label":"Claude","plan_type":"max","account_status":"active","quota":{"windows":{"five_hour":{"utilization_pct":10.0,"resets_at":"2026-07-11T15:00:00Z"},"seven_day":{"utilization_pct":20.0,"resets_at":"2026-07-18T10:00:00Z"},"binding":{"utilization_pct":45.0,"resets_at":"2026-07-11T12:00:00Z","resets_in":"2h30m"}}}}]}
JSON
    ;;
  empty) printf '%s\n' '{"status":"ok","accounts":[]}' ;;
  malformed) printf '%s\n' 'this is not JSON' ;;
  error_shape) printf '%s\n' '{"status":"error","errors":[{"message":"upstream unavailable"}]}' ;;
  failure) exit 22 ;;
esac
EOF
chmod +x "$TMP_DIR/bin/curl"

PASS=0
FAIL=0
pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }
contains() { [[ "$1" == *"$2"* ]]; }

echo "── quota endpoint OpenAPI ──"

python3 - "$REPO_DIR/docs/openapi/gateway-engine.yaml" <<'PY'
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as spec_file:
    spec = yaml.safe_load(spec_file)

assert any(
    server.get("url") == "https://gateway.infra.plexplease.com"
    for server in spec["servers"]
), "production Gateway Engine server is not documented"

operation = spec["paths"]["/admin/quota/status"]["get"]
admin_key = next(
    parameter
    for parameter in operation["parameters"]
    if parameter["name"] == "x-admin-key" and parameter["in"] == "header"
)
assert admin_key["required"] is False, "x-admin-key must be documented as optional"

success = operation["responses"]["200"]["content"]["application/json"]
example = success["example"]
account = example["accounts"][0]
assert example["captured_at"]
assert account["email"] and account["account_status"]
assert account["quota"]["windows"]["five_hour"]["utilization_pct"] == 10.0
assert account["quota"]["windows"]["binding"]["resets_in"] == "3h59m"
assert "models" not in account["quota"], "success example must omit absent optional models"
assert "full_quota_error" not in account["quota"], "success example must omit absent optional full_quota_error"

for status in ("403", "502", "503"):
    assert status in operation["responses"], f"response {status} is not documented"

for status in ("403", "503"):
    error_response = operation["responses"][status]["content"]["application/json"]
    error_schema = error_response["schema"]
    assert set(error_schema["required"]) == {"error"}
    error_properties = error_schema["properties"]["error"]
    assert set(error_properties["required"]) == {"message", "code"}
    assert set(error_properties["properties"]) >= {"message", "code"}
    assert error_response["example"]["error"]["code"] == "admin_key_required"

dependency_error = operation["responses"]["502"]["content"]["application/json"]
dependency_schema = dependency_error["schema"]
assert set(dependency_schema["required"]) == {"status", "errors"}
assert dependency_schema["properties"]["status"]["enum"] == ["error"]
dependency_error_item = dependency_schema["properties"]["errors"]["items"]
assert set(dependency_error_item["required"]) == {"code", "message", "location"}
assert dependency_error["example"]["status"] == "error"
assert dependency_error["example"]["errors"][0]["code"] == "cliproxy_fetch_error"

quota_properties = success["schema"]["properties"]["accounts"]["items"]["properties"]["quota"]["properties"]
for field in (
    "captured_at",
    "stale",
    "windows",
    "tokens_remaining",
    "tokens_limit",
    "requests_remaining",
    "requests_limit",
    "models",
    "full_quota_error",
):
    assert field in quota_properties, f"quota field {field} is not documented"
assert "errors" in success["schema"]["properties"], "partial errors are not documented"
PY
pass "documents the production quota endpoint contract and examples"

run_summary() {
  local scenario="$1" url="$2" key="${3:-}"
  FAKE_CURL_SCENARIO="$scenario" \
  FAKE_CURL_ARGS="$TMP_DIR/curl-args" \
  FAKE_CURL_STDIN="$TMP_DIR/curl-stdin" \
  GATEWAY_ENGINE_URL="$url" \
  GATEWAY_ENGINE_ADMIN_KEY="$key" \
  HOME="$TMP_DIR/home" \
  PATH="$TMP_DIR/bin:$PATH" \
    bash "$TMP_DIR/cliproxy-setup.sh" quota-summary 2>&1
}

echo "── quota-summary helper ──"

production_url="https://gateway.infra.plexplease.com"
output=$(run_summary accounts "$production_url/") || true
args=$(cat "$TMP_DIR/curl-args")
if contains "$args" "$production_url/admin/quota/status" && \
   ! contains "$args" "x-admin-key"; then
  pass "uses the exact production Gateway Engine URL without an empty admin header"
else
  fail "expected production Gateway Engine quota URL and no admin header (args: $args)"
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
curl_stdin=$(cat "$TMP_DIR/curl-stdin")
if contains "$args" "-H" && contains "$args" "@-" && \
   ! contains "$args" "$secret" && contains "$curl_stdin" "x-admin-key: $secret" && \
   ! contains "$output" "$secret"; then
  pass "sends the admin key through curl stdin, never argv or output"
else
  fail "expected a stdin-only x-admin-key header (args: $args; stdin: $curl_stdin; output: $output)"
fi

if contains "$output" "no accounts found"; then
  pass "handles an empty account list"
else
  fail "expected an empty-account explanation (output: $output)"
fi

help_output=$(HOME="$TMP_DIR/home" PATH="$TMP_DIR/bin:$PATH" bash "$TMP_DIR/cliproxy-setup.sh" help)
if contains "$help_output" "quota-summary" && \
   contains "$help_output" "Per-account quota windows and reset timing" && \
   ! contains "$help_output" "Per-credential request counts and last-refresh timestamps"; then
  pass "describes quota-summary account windows and reset timing in help"
else
  fail "expected accurate quota-summary help text (output: $help_output)"
fi

for scenario in malformed error_shape; do
  set +e
  output=$(run_summary "$scenario" "https://gateway.example.test")
  status=$?
  set -e
  if [[ "$status" -ne 0 ]] && contains "$output" "ERROR: Gateway Engine response" && \
     ! contains "$output" "Traceback" && ! contains "$output" "Per-account quota summary"; then
    pass "rejects $scenario 2xx payload without traceback or premature summary"
  else
    fail "expected concise rejection for $scenario payload (status=$status; output: $output)"
  fi
done

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
