#!/usr/bin/env bash
# Fake curl for offline tests/test_deep_smoke.py runs.
#
# deep-smoke.sh always calls curl with the target URL as the final argument
# and appends `-w '\n%{http_code}'`, so this fake only inspects the last
# argument and prints "<body>\n<code>" to match that convention. Responses
# are controlled entirely via env vars so tests can drive every scenario
# without touching the network.
set -euo pipefail

url="${*: -1}"

body=""
code="200"

case "$url" in
  */health)
    code="${FAKE_HEALTH_CODE:-200}"
    ;;
  */health/ready)
    code="${FAKE_READY_CODE:-200}"
    ;;
  */version)
    code="${FAKE_VERSION_CODE:-200}"
    body="${FAKE_VERSION_BODY-}"
    if [ -z "$body" ]; then
      body='{"version":"1.0","git_sha":"abc1234","display_version":"1.0 (abc1234)"}'
    fi
    ;;
  */v1/models)
    code="${FAKE_MODELS_CODE:-200}"
    body="${FAKE_MODELS_BODY-}"
    if [ -z "$body" ]; then
      body='{"data":[{"id":"AI-Gateway:claude-sonnet-4-6"}]}'
    fi
    ;;
  */v1/chat/completions)
    code="${FAKE_COMPLETION_CODE:-200}"
    body="${FAKE_COMPLETION_BODY-}"
    if [ -z "$body" ]; then
      body='{"choices":[{"message":{"content":"pong"}}]}'
    fi
    ;;
  *)
    code="404"
    body='{"error":"not found in fake_curl.sh"}'
    ;;
esac

printf '%s\n%s' "$body" "$code"
