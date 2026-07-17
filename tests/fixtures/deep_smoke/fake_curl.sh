#!/usr/bin/env bash
# Fake curl for offline tests/test_deep_smoke.py runs.
#
# deep-smoke.sh always calls curl with the target URL as the final argument
# and appends `-w '\n%{http_code}'`, so this fake only inspects the last
# argument (URL) and the -d/--data payload (for chat completions routing) and
# prints "<body>\n<code>" to match that convention. Responses are controlled
# entirely via env vars so tests can drive every scenario without touching
# the network.
#
# Model-specific overrides for /v1/chat/completions: set
# FAKE_COMPLETION_CODE_<SANITIZED_MODEL> / FAKE_COMPLETION_BODY_<SANITIZED_MODEL>
# where SANITIZED_MODEL is the model id upper-cased with non-alnum -> '_'
# (e.g. "claude-sonnet-4-6" -> "CLAUDE_SONNET_4_6"). Falls back to the plain
# FAKE_COMPLETION_CODE / FAKE_COMPLETION_BODY when no per-model override is set.
#
# Set FAKE_CURL_LOG=/path/to/file to append "<url> <payload> <admin_key_header>"
# for every call (used by tests asserting the end_user smoke tag was sent,
# and that admin checks forward x-admin-key when DEEP_SMOKE_ADMIN_KEY is set).
set -uo pipefail

url="${*: -1}"

payload=""
admin_key_header=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-d" ] || [ "$prev" = "--data" ]; then
    payload="$arg"
  fi
  if [ "$prev" = "-H" ]; then
    case "$arg" in
      x-admin-key:*) admin_key_header="${arg#x-admin-key: }" ;;
    esac
  fi
  prev="$arg"
done

if [ -n "${FAKE_CURL_LOG:-}" ]; then
  printf '%s %s %s\n' "$url" "$payload" "$admin_key_header" >>"$FAKE_CURL_LOG"
fi

sanitize() {
  printf '%s' "$1" | tr '[:lower:]' '[:upper:]' | tr -c 'A-Za-z0-9' '_'
}

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
    if printf '%s' "$payload" | grep -q '"stream":true'; then
      code="${FAKE_STREAM_CODE:-200}"
      body="${FAKE_STREAM_BODY-}"
      if [ -z "$body" ]; then
        body=$'data: {"choices":[{"delta":{"content":"pong"},"finish_reason":null}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
      fi
    else
      model=$(printf '%s' "$payload" | sed -n 's/.*"model":"\([^"]*\)".*/\1/p')
      model_key=$(sanitize "$model")
      code_var="FAKE_COMPLETION_CODE_${model_key}"
      body_var="FAKE_COMPLETION_BODY_${model_key}"
      code_override="${!code_var-}"
      body_override="${!body_var-}"
      code="${code_override:-${FAKE_COMPLETION_CODE:-200}}"
      body="${body_override:-${FAKE_COMPLETION_BODY-}}"
      if [ -z "$body" ]; then
        body='{"id":"chatcmpl-fake-000","choices":[{"message":{"content":"pong"},"finish_reason":"stop"}]}'
      fi
    fi
    ;;
  */v1/responses)
    code="${FAKE_RESPONSES_CODE:-200}"
    body="${FAKE_RESPONSES_BODY-}"
    if [ -z "$body" ]; then
      body='{"id":"resp_abc","object":"response","status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"pong"}]}]}'
    fi
    ;;
  */v1/messages)
    code="${FAKE_MESSAGES_CODE:-200}"
    body="${FAKE_MESSAGES_BODY-}"
    if [ -z "$body" ]; then
      body='{"id":"msg_abc","type":"message","role":"assistant","content":[{"type":"text","text":"pong"}],"stop_reason":"end_turn"}'
    fi
    ;;
  */admin/status)
    code="${FAKE_ADMIN_STATUS_CODE:-200}"
    body="${FAKE_ADMIN_STATUS_BODY-}"
    if [ -z "$body" ]; then
      body='{"schema_version":"admin-console.v1","generated_at":"2026-07-17T00:00:00Z","panels":{}}'
    fi
    ;;
  */admin/credentials)
    code="${FAKE_ADMIN_CREDENTIALS_CODE:-200}"
    body="${FAKE_ADMIN_CREDENTIALS_BODY-}"
    if [ -z "$body" ]; then
      body='{"credentials":[]}'
    fi
    ;;
  */admin/quota/status)
    code="${FAKE_ADMIN_QUOTA_CODE:-200}"
    body="${FAKE_ADMIN_QUOTA_BODY-}"
    if [ -z "$body" ]; then
      body='{"status":"ok","source":"cliproxy","captured_at":"2026-07-17T00:00:00Z","partial":false,"accounts":[]}'
    fi
    ;;
  *)
    code="404"
    body='{"error":"not found in fake_curl.sh"}'
    ;;
esac

printf '%s\n%s' "$body" "$code"
