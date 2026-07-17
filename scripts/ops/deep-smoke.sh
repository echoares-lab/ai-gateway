#!/usr/bin/env bash
#
# deep-smoke.sh — operator deep-smoke entrypoint.
#
# Staging `--full` is the promote gate before pinning digests to production;
# `--quick` covers the incident / health-check path on staging or prod. See
# docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md.
#
# Usage:
#   ./scripts/ops/deep-smoke.sh [--env staging|prod] [--quick|--full] \
#       [--strict] [--allow-mutating-admin]
#
# Flags:
#   --env staging|prod     target environment (default: staging)
#   --quick                health, ready, version, models, one tagged cheap
#                           completion, kubectl pods Ready (default mode)
#   --full                 --quick plus: tagged API-shape checks for
#                           /v1/chat/completions, /v1/responses, and
#                           /v1/messages; one SSE streaming chat completion;
#                           cheap completions for the claude/gpt/gemini
#                           provider-family allowlist; read-mostly admin
#                           checks (GET /admin/status 2xx, GET
#                           /admin/credentials non-error, and a SOFT GET
#                           /admin/quota/status check — 2xx + JSON object
#                           only, no field contracts asserted; see
#                           check_admin_quota_payload in deep_smoke.py);
#                           a cluster Jobs check (bootstrap/migration Jobs,
#                           e.g. litellm-migrate/gateway-migrate, must not be
#                           Failed when present); and a LiteLLM_SpendLogs DB
#                           side-effect check (a recent row must exist
#                           matching the tagged completion's end_user and/or
#                           request_id — see check_spendlogs in
#                           deep_smoke.py). On staging, the Jobs and
#                           SpendLogs checks are a HARD requirement: missing
#                           kubectl/DB access is a FAIL, not a WARN (see
#                           DEEP_SMOKE_PG_* below). Langfuse checks are
#                           tracked separately under bundle #396.
#   --strict               treat soft warnings (e.g. missing kubectl) as
#                           failures instead of warnings
#   --allow-mutating-admin reserved for future --full admin probes; no
#                           effect on --quick or the current --full checks
#
# Env vars (placeholders documented in .env.example, never commit secrets):
#   DEEP_SMOKE_GATEWAY_URL      override default staging/prod gateway URL
#   DEEP_SMOKE_API_KEY          bearer key used for /v1 requests
#   DEEP_SMOKE_ADMIN_KEY        x-admin-key sent with --full admin checks
#                               (/admin/status, /admin/credentials,
#                               /admin/quota/status); omit if
#                               GATEWAY_ENGINE_ADMIN_READ_AUTH is not enabled
#   DEEP_SMOKE_K8S_NAMESPACE    override target kube namespace
#   DEEP_SMOKE_KUBE_CONTEXT     optional kubectl context
#   DEEP_SMOKE_MODELS           comma-separated model id override; first
#                               entry is used for the quick completion check
#   DEEP_SMOKE_RESPONSES_MODEL  model id used for the --full /v1/responses
#                               shape check (default: gpt-5-4)
#   DEEP_SMOKE_MESSAGES_MODEL   model id used for the --full /v1/messages
#                               shape check (default: claude-sonnet-4-6)
#   DEEP_SMOKE_STREAM_MODEL     model id used for the --full SSE streaming
#                               check (default: same as DEEP_SMOKE_MODELS)
#   DEEP_SMOKE_PROVIDER_MODELS  comma-separated family=model pairs for the
#                               --full provider-family allowlist (default:
#                               claude=claude-sonnet-4-6,gpt=gpt-5-4,
#                               gemini=gemini-3-flash)
#   DEEP_SMOKE_PODS_ALLOWLIST   comma-separated pod-name substrings to skip
#                               in the pods-Ready check
#   DEEP_SMOKE_SKIP_PODS        set to "1" to skip the kubectl pods check
#                               (recorded as a warning)
#   DEEP_SMOKE_JOBS_ALLOWLIST   comma-separated Job-name substrings to skip
#                               in the --full cluster Jobs check
#   DEEP_SMOKE_SKIP_JOBS        set to "1" to skip the --full cluster Jobs
#                               check (recorded as a warning)
#   DEEP_SMOKE_PG_NAMESPACE     kube namespace to exec into for the
#                               LiteLLM_SpendLogs check (default: "database";
#                               staging/prod share a central Postgres — see
#                               docs/CICD_PHASE2_STAGING.md § Databases)
#   DEEP_SMOKE_PG_POD           exact Postgres pod name; when set, skips the
#                               label-selector lookup below entirely
#   DEEP_SMOKE_PG_POD_SELECTOR  label selector used to find the Postgres pod
#                               when DEEP_SMOKE_PG_POD is unset (default:
#                               "cnpg.io/cluster=platform-postgres,role=primary")
#   DEEP_SMOKE_PG_CONTAINER     container name within the Postgres pod to
#                               exec into (default: "postgres")
#   DEEP_SMOKE_PG_USER          psql -U user for the SpendLogs query
#                               (default: "postgres"); use a scoped
#                               read-only role in production if available
#   DEEP_SMOKE_PG_DB            database to query (default:
#                               "litellm_staging" on --env staging,
#                               "litellm" on --env prod)
#   DEEP_SMOKE_SPENDLOGS_WINDOW_MINUTES  only LiteLLM_SpendLogs rows within
#                               this many trailing minutes count as a match
#                               (default: 15)
#   DEEP_SMOKE_SKIP_SPENDLOGS   set to "1" to skip the --full
#                               LiteLLM_SpendLogs DB check (recorded as a
#                               warning)
#   DEEP_SMOKE_EXPECT_GIT_SHA   when set, GET /version must report a matching
#                               git_sha (full SHA or unique prefix). Used by
#                               the CI promote gate to ensure staging is on the
#                               candidate revision before digest pin.
#   DEEP_SMOKE_KUBECTL_BIN      override kubectl binary (tests only)
#   DEEP_SMOKE_PYTHON_BIN       override python3 binary (tests only)
#
# Exit codes: 0 = all checks passed; 1 = at least one check failed (or a
# warning was promoted to failure by --strict); 2 = usage/argument error.
#
# Note on staging vs. prod for the Jobs/SpendLogs checks: on `--env staging`
# `--full` (the promote gate), missing kubectl or a failed DB query is a
# hard FAIL regardless of --strict — staging --full is expected to always
# have cluster/DB access. On `--env prod` `--full` (incident/optional use),
# the same unavailability is a WARN unless --strict is passed, matching the
# existing --quick pods-check behavior.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEEP_SMOKE_PY="$SCRIPT_DIR/deep_smoke.py"
PYTHON_BIN="${DEEP_SMOKE_PYTHON_BIN:-python3}"
CURL_BIN="${DEEP_SMOKE_CURL_BIN:-curl}"
KUBECTL_BIN="${DEEP_SMOKE_KUBECTL_BIN:-kubectl}"
DEFAULT_QUICK_MODEL="gpt-5-4"
DEFAULT_RESPONSES_MODEL="gpt-5-4"
DEFAULT_MESSAGES_MODEL="claude-sonnet-4-6"
DEFAULT_PROVIDER_MODELS="claude=claude-sonnet-4-6,gpt=gpt-5-4,gemini=gemini-3-flash"
DEFAULT_PG_NAMESPACE="database"
DEFAULT_PG_POD_SELECTOR="cnpg.io/cluster=platform-postgres,role=primary"
DEFAULT_PG_CONTAINER="postgres"
DEFAULT_PG_USER="postgres"
DEFAULT_SPENDLOGS_WINDOW_MINUTES="15"

ENVIRONMENT="staging"
MODE="quick"
STRICT=0
ALLOW_MUTATING_ADMIN=0

usage() {
  sed -n '2,110p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --env)
      ENVIRONMENT="${2:?--env requires a value}"
      shift 2
      ;;
    --quick)
      MODE="quick"
      shift
      ;;
    --full)
      MODE="full"
      shift
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    --allow-mutating-admin)
      ALLOW_MUTATING_ADMIN=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument '$1' (try --help)" >&2
      exit 2
      ;;
  esac
done

case "$ENVIRONMENT" in
  staging | prod) ;;
  *)
    echo "error: --env must be 'staging' or 'prod' (got '$ENVIRONMENT')" >&2
    exit 2
    ;;
esac

if [ "$ENVIRONMENT" = "staging" ]; then
  DEFAULT_URL="https://gateway-staging.infra.plexplease.com"
  DEFAULT_NAMESPACE="ai-gateway-staging"
  DEFAULT_PG_DB="litellm_staging"
else
  DEFAULT_URL="https://gateway.infra.plexplease.com"
  DEFAULT_NAMESPACE="ai-gateway"
  DEFAULT_PG_DB="litellm"
fi

GATEWAY_URL="${DEEP_SMOKE_GATEWAY_URL:-$DEFAULT_URL}"
GATEWAY_URL="${GATEWAY_URL%/}"
NAMESPACE="${DEEP_SMOKE_K8S_NAMESPACE:-$DEFAULT_NAMESPACE}"
API_KEY="${DEEP_SMOKE_API_KEY:-}"
ADMIN_KEY="${DEEP_SMOKE_ADMIN_KEY:-}"
KUBE_CONTEXT="${DEEP_SMOKE_KUBE_CONTEXT:-}"
PG_NAMESPACE="${DEEP_SMOKE_PG_NAMESPACE:-$DEFAULT_PG_NAMESPACE}"
PG_POD="${DEEP_SMOKE_PG_POD:-}"
PG_POD_SELECTOR="${DEEP_SMOKE_PG_POD_SELECTOR:-$DEFAULT_PG_POD_SELECTOR}"
PG_CONTAINER="${DEEP_SMOKE_PG_CONTAINER:-$DEFAULT_PG_CONTAINER}"
PG_USER="${DEEP_SMOKE_PG_USER:-$DEFAULT_PG_USER}"
PG_DB="${DEEP_SMOKE_PG_DB:-$DEFAULT_PG_DB}"
SMOKE_TAG="deep-smoke-$(date -u +%Y%m%dT%H%M%SZ)"
LAST_REQUEST_ID=""

CHECK_NAMES=()
CHECK_STATUSES=() # PASS | FAIL | WARN
CHECK_DETAILS=()

record() {
  CHECK_NAMES+=("$1")
  CHECK_STATUSES+=("$2")
  CHECK_DETAILS+=("$3")
}

# Maps a deep_smoke.py exit code (0/1/2) to a PASS/FAIL/WARN label.
map_rc_to_status() {
  case "$1" in
    0) echo "PASS" ;;
    2) echo "WARN" ;;
    *) echo "FAIL" ;;
  esac
}

# Splits "<body>\n<http_code>" (curl -w '\n%{http_code}' convention) into the
# globals $body / $code. Empty input (e.g. connection failure) -> code=000.
parse_response() {
  local raw="$1"
  if [ -z "$raw" ]; then
    body=""
    code="000"
    return
  fi
  code="${raw##*$'\n'}"
  body="${raw%$'\n'*}"
}

# GET/POST $2 (path) against $GATEWAY_URL, optionally with a JSON body ($3).
# Pass $4=1 to also send x-admin-key (when DEEP_SMOKE_ADMIN_KEY is set) for
# admin routes. Always succeeds (never trips `set -e`) — the caller inspects
# the trailing HTTP status line produced by `-w '\n%{http_code}'`.
http_call() {
  local method="$1" path="$2" data="${3:-}" want_admin_key="${4:-0}"
  local curl_args=(-sS --max-time 20 -w '\n%{http_code}' -X "$method")
  if [ -n "$API_KEY" ]; then
    curl_args+=(-H "Authorization: Bearer $API_KEY")
  fi
  if [ "$want_admin_key" = "1" ] && [ -n "$ADMIN_KEY" ]; then
    curl_args+=(-H "x-admin-key: $ADMIN_KEY")
  fi
  if [ -n "$data" ]; then
    curl_args+=(-H "Content-Type: application/json" -d "$data")
  fi
  curl_args+=("$GATEWAY_URL$path")
  "$CURL_BIN" "${curl_args[@]}" 2>/dev/null || true
}

# True (rc 0) when $1 is a 2xx HTTP status code string.
is_2xx() {
  case "$1" in
    2??) return 0 ;;
    *) return 1 ;;
  esac
}

# Runs `deep_smoke.py $subcmd` with $input piped to stdin. Sets
# $CAPTURED_OUT / $CAPTURED_RC without tripping `set -e` on a non-zero exit
# (deep_smoke.py uses non-zero exits for expected FAIL/WARN outcomes).
py_check() {
  local subcmd="$1"
  shift
  local input="$1"
  shift
  CAPTURED_OUT=$(printf '%s' "$input" | "$PYTHON_BIN" "$DEEP_SMOKE_PY" "$subcmd" "$@") && CAPTURED_RC=0 || CAPTURED_RC=$?
}

check_health() {
  local raw
  raw=$(http_call GET "/health")
  parse_response "$raw"
  if [ "$code" = "200" ]; then
    record "health" PASS "GET /health -> 200"
  else
    record "health" FAIL "GET /health -> ${code:-000}"
  fi
}

check_ready() {
  local raw
  raw=$(http_call GET "/health/ready")
  parse_response "$raw"
  if [ "$code" = "200" ]; then
    record "ready" PASS "GET /health/ready -> 200"
  else
    record "ready" FAIL "GET /health/ready -> ${code:-000}"
  fi
}

check_version() {
  local raw
  raw=$(http_call GET "/version")
  parse_response "$raw"
  if [ "$code" != "200" ]; then
    record "version" FAIL "GET /version -> ${code:-000}"
    return
  fi
  local expect_args=()
  if [ -n "${DEEP_SMOKE_EXPECT_GIT_SHA:-}" ]; then
    expect_args+=(--expect-git-sha "${DEEP_SMOKE_EXPECT_GIT_SHA}")
  fi
  py_check check-version "$body" "${expect_args[@]}"
  record "version" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

check_models() {
  local raw
  raw=$(http_call GET "/v1/models")
  parse_response "$raw"
  if [ "$code" != "200" ]; then
    record "models" FAIL "GET /v1/models -> ${code:-000}"
    return
  fi
  py_check check-models "$body"
  record "models" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

check_completion() {
  local model raw payload
  model="${DEEP_SMOKE_MODELS:-}"
  model="${model%%,*}"
  model="${model:-$DEFAULT_QUICK_MODEL}"
  payload=$(printf '{"model":"%s","messages":[{"role":"user","content":"ping"}],"max_tokens":8,"user":"%s"}' \
    "$model" "$SMOKE_TAG")
  raw=$(http_call POST "/v1/chat/completions" "$payload")
  parse_response "$raw"
  if [ "$code" != "200" ]; then
    record "completion" FAIL "POST /v1/chat/completions ($model) -> ${code:-000}"
    return
  fi
  # Best-effort request-id capture for the --full SpendLogs check
  # (check_spendlogs below): LiteLLM's completion response "id" is what ends
  # up in LiteLLM_SpendLogs.request_id. Left empty (never fails this check)
  # if the field is absent — check_spendlogs falls back to end_user=$SMOKE_TAG.
  LAST_REQUEST_ID=$(printf '%s' "$body" | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
  py_check check-completion "$body"
  record "completion" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

check_responses_shape() {
  local model raw payload
  model="${DEEP_SMOKE_RESPONSES_MODEL:-$DEFAULT_RESPONSES_MODEL}"
  # metadata.user is best-effort tagging for upstream/provider logs; the
  # gateway-engine's Responses API -> Chat Completions converter does not
  # currently forward it into the end_user field LiteLLM_SpendLogs uses, so
  # check_spendlogs (issue #401) only verifies the DB side effect of the
  # plain /v1/chat/completions call in check_completion above, not this one.
  payload=$(printf '{"model":"%s","input":"ping","max_output_tokens":8,"metadata":{"user":"%s"}}' \
    "$model" "$SMOKE_TAG")
  raw=$(http_call POST "/v1/responses" "$payload")
  parse_response "$raw"
  if [ "$code" != "200" ]; then
    record "responses_shape" FAIL "POST /v1/responses ($model) -> ${code:-000}"
    return
  fi
  py_check check-responses "$body"
  record "responses_shape" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

check_messages_shape() {
  local model raw payload
  model="${DEEP_SMOKE_MESSAGES_MODEL:-$DEFAULT_MESSAGES_MODEL}"
  # metadata.user_id is best-effort tagging; see check_responses_shape note.
  payload=$(printf '{"model":"%s","max_tokens":8,"messages":[{"role":"user","content":"ping"}],"metadata":{"user_id":"%s"}}' \
    "$model" "$SMOKE_TAG")
  raw=$(http_call POST "/v1/messages" "$payload")
  parse_response "$raw"
  if [ "$code" != "200" ]; then
    record "messages_shape" FAIL "POST /v1/messages ($model) -> ${code:-000}"
    return
  fi
  py_check check-messages "$body"
  record "messages_shape" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

check_stream() {
  local model raw payload
  model="${DEEP_SMOKE_STREAM_MODEL:-$DEFAULT_QUICK_MODEL}"
  payload=$(printf '{"model":"%s","messages":[{"role":"user","content":"ping"}],"max_tokens":8,"stream":true,"user":"%s"}' \
    "$model" "$SMOKE_TAG")
  raw=$(http_call POST "/v1/chat/completions" "$payload")
  parse_response "$raw"
  if [ "$code" != "200" ]; then
    record "stream" FAIL "POST /v1/chat/completions stream ($model) -> ${code:-000}"
    return
  fi
  py_check check-stream "$body"
  record "stream" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

# Cheap tagged completion per claude/gpt/gemini family (or DEEP_SMOKE_PROVIDER_MODELS
# override). Each pair is "family=model"; records one check per family so a single
# provider outage doesn't mask the others.
check_provider_families() {
  local spec pair family model raw payload
  spec="${DEEP_SMOKE_PROVIDER_MODELS:-$DEFAULT_PROVIDER_MODELS}"
  local pairs
  IFS=',' read -ra pairs <<<"$spec"
  for pair in "${pairs[@]}"; do
    [ -z "$pair" ] && continue
    family="${pair%%=*}"
    model="${pair#*=}"
    if [ -z "$family" ] || [ -z "$model" ] || [ "$family" = "$pair" ]; then
      record "provider_${pair:-unknown}" FAIL "invalid DEEP_SMOKE_PROVIDER_MODELS entry '$pair' (expected family=model)"
      continue
    fi
    payload=$(printf '{"model":"%s","messages":[{"role":"user","content":"ping"}],"max_tokens":8,"user":"%s"}' \
      "$model" "$SMOKE_TAG")
    raw=$(http_call POST "/v1/chat/completions" "$payload")
    parse_response "$raw"
    if [ "$code" != "200" ]; then
      record "provider_${family}" FAIL "POST /v1/chat/completions ($model) -> ${code:-000}"
      continue
    fi
    py_check check-completion "$body"
    record "provider_${family}" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT ($model)"
  done
}

# Read-mostly admin checks (issue #400, bundle #396). /admin/status and
# /admin/credentials require 2xx + non-error JSON; /admin/quota/status is
# SOFT — 2xx + JSON object only, no field contracts (schema still in flux,
# hardening tracked as issue #403). See check_admin_*_payload in
# deep_smoke.py for the exact soft-contract semantics.
check_admin_status() {
  local raw
  raw=$(http_call GET "/admin/status" "" 1)
  parse_response "$raw"
  if ! is_2xx "$code"; then
    record "admin_status" FAIL "GET /admin/status -> ${code:-000}"
    return
  fi
  py_check check-admin-status "$body"
  record "admin_status" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

check_admin_credentials() {
  local raw
  raw=$(http_call GET "/admin/credentials" "" 1)
  parse_response "$raw"
  if ! is_2xx "$code"; then
    record "admin_credentials" FAIL "GET /admin/credentials -> ${code:-000}"
    return
  fi
  py_check check-admin-credentials "$body"
  record "admin_credentials" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

check_admin_quota() {
  local raw
  raw=$(http_call GET "/admin/quota/status" "" 1)
  parse_response "$raw"
  if ! is_2xx "$code"; then
    record "admin_quota" FAIL "GET /admin/quota/status -> ${code:-000}"
    return
  fi
  py_check check-admin-quota "$body"
  record "admin_quota" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

check_pods() {
  if [ "${DEEP_SMOKE_SKIP_PODS:-0}" = "1" ]; then
    record "pods" WARN "skipped via DEEP_SMOKE_SKIP_PODS=1"
    return
  fi

  if ! command -v "$KUBECTL_BIN" >/dev/null 2>&1; then
    if [ "$STRICT" = "1" ]; then
      record "pods" FAIL "kubectl binary '$KUBECTL_BIN' not found (required with --strict)"
    else
      record "pods" WARN "kubectl binary '$KUBECTL_BIN' not found; skipping pod readiness check"
    fi
    return
  fi

  local kube_args=()
  if [ -n "$KUBE_CONTEXT" ]; then
    kube_args+=(--context "$KUBE_CONTEXT")
  fi
  kube_args+=(-n "$NAMESPACE" get pods -o json)

  local out rc
  out=$("$KUBECTL_BIN" "${kube_args[@]}" 2>&1) && rc=0 || rc=$?
  if [ "$rc" -ne 0 ]; then
    record "pods" FAIL "kubectl get pods failed (exit $rc): $(printf '%s' "$out" | head -c 200)"
    return
  fi

  py_check check-pods "$out" --allowlist "${DEEP_SMOKE_PODS_ALLOWLIST:-}"
  record "pods" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

# Cluster Job checks (issue #401, bundle #396): bootstrap/migration Jobs
# (e.g. a Postgres bootstrap PreSync hook, litellm-migrate, gateway-migrate —
# see docs/CICD_PHASE2_STAGING.md) must not be Failed when present. Pods
# Ready is already covered by check_pods above; this only adds the
# Job-specific Failed-condition assertion. Unlike check_pods (WARN on
# missing kubectl even on staging), a missing kubectl here is a hard FAIL on
# staging --full per the promote-gate contract — see the env var docs above.
check_jobs() {
  if [ "${DEEP_SMOKE_SKIP_JOBS:-0}" = "1" ]; then
    record "jobs" WARN "skipped via DEEP_SMOKE_SKIP_JOBS=1"
    return
  fi

  if ! command -v "$KUBECTL_BIN" >/dev/null 2>&1; then
    if [ "$ENVIRONMENT" = "staging" ] || [ "$STRICT" = "1" ]; then
      record "jobs" FAIL "kubectl binary '$KUBECTL_BIN' not found; the cluster Jobs check requires kubectl on staging --full (or with --strict)"
    else
      record "jobs" WARN "kubectl binary '$KUBECTL_BIN' not found; skipping cluster Jobs check"
    fi
    return
  fi

  local kube_args=()
  if [ -n "$KUBE_CONTEXT" ]; then
    kube_args+=(--context "$KUBE_CONTEXT")
  fi
  kube_args+=(-n "$NAMESPACE" get jobs -o json)

  local out rc
  out=$("$KUBECTL_BIN" "${kube_args[@]}" 2>&1) && rc=0 || rc=$?
  if [ "$rc" -ne 0 ]; then
    record "jobs" FAIL "kubectl get jobs failed (exit $rc): $(printf '%s' "$out" | head -c 200)"
    return
  fi

  py_check check-jobs "$out" --allowlist "${DEEP_SMOKE_JOBS_ALLOWLIST:-}"
  record "jobs" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

# Escapes a value as a single-quoted SQL string literal for the psql query in
# check_spendlogs below (doubling embedded single quotes). An empty value
# becomes bare SQL NULL so an unset end_user/request_id never matches an
# empty-string DB column via `= ''`.
sql_quote() {
  local value="$1"
  if [ -z "$value" ]; then
    printf 'NULL'
    return
  fi
  printf "'%s'" "${value//\'/\'\'}"
}

# DB side-effect check (issue #401, bundle #396): after the tagged
# check_completion call above, poll public."LiteLLM_SpendLogs" (see
# db/seed-litellm-mock.sql) via `kubectl exec` into the Postgres pod + psql
# for a row matching the smoke end_user ($SMOKE_TAG) and/or request_id
# ($LAST_REQUEST_ID) within a short recency window. This proves the tagged
# request actually reached LiteLLM and was logged, not just that the HTTP
# call returned 200.
#
# Hard requirement on staging --full (promote gate): kubectl and DB access
# are both required; a FAIL here (not a WARN) on missing/failing either,
# regardless of --strict. On prod --full (incident/optional use), the same
# unavailability is a WARN unless --strict is passed — matching check_pods.
check_spendlogs() {
  if [ "${DEEP_SMOKE_SKIP_SPENDLOGS:-0}" = "1" ]; then
    record "spendlogs" WARN "skipped via DEEP_SMOKE_SKIP_SPENDLOGS=1"
    return
  fi

  if [ -z "$SMOKE_TAG" ] && [ -z "$LAST_REQUEST_ID" ]; then
    record "spendlogs" FAIL "no smoke end_user/request_id available to match against LiteLLM_SpendLogs"
    return
  fi

  if ! command -v "$KUBECTL_BIN" >/dev/null 2>&1; then
    if [ "$ENVIRONMENT" = "staging" ] || [ "$STRICT" = "1" ]; then
      record "spendlogs" FAIL "kubectl binary '$KUBECTL_BIN' not found; the LiteLLM_SpendLogs check requires kubectl on staging --full (or with --strict)"
    else
      record "spendlogs" WARN "kubectl binary '$KUBECTL_BIN' not found; skipping LiteLLM_SpendLogs check"
    fi
    return
  fi

  local kube_args=()
  if [ -n "$KUBE_CONTEXT" ]; then
    kube_args+=(--context "$KUBE_CONTEXT")
  fi

  local pg_pod="$PG_POD"
  if [ -z "$pg_pod" ]; then
    local lookup_rc
    pg_pod=$("$KUBECTL_BIN" "${kube_args[@]}" -n "$PG_NAMESPACE" get pods -l "$PG_POD_SELECTOR" \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null) && lookup_rc=0 || lookup_rc=$?
    if [ "$lookup_rc" -ne 0 ] || [ -z "$pg_pod" ]; then
      if [ "$ENVIRONMENT" = "staging" ] || [ "$STRICT" = "1" ]; then
        record "spendlogs" FAIL "could not resolve Postgres pod (namespace '$PG_NAMESPACE', selector '$PG_POD_SELECTOR'); set DEEP_SMOKE_PG_POD to override"
      else
        record "spendlogs" WARN "could not resolve Postgres pod; skipping LiteLLM_SpendLogs check"
      fi
      return
    fi
  fi

  local query
  query=$(printf 'SELECT coalesce(json_agg(row_to_json(t)), '"'"'[]'"'"') FROM (SELECT request_id, end_user, "startTime" FROM public."LiteLLM_SpendLogs" WHERE end_user = %s OR request_id = %s ORDER BY "startTime" DESC LIMIT 20) t;' \
    "$(sql_quote "$SMOKE_TAG")" "$(sql_quote "$LAST_REQUEST_ID")")

  local out rc
  out=$("$KUBECTL_BIN" "${kube_args[@]}" -n "$PG_NAMESPACE" exec "$pg_pod" -c "$PG_CONTAINER" -- \
    psql -U "$PG_USER" -d "$PG_DB" -t -A -c "$query" 2>&1) && rc=0 || rc=$?
  if [ "$rc" -ne 0 ]; then
    if [ "$ENVIRONMENT" = "staging" ] || [ "$STRICT" = "1" ]; then
      record "spendlogs" FAIL "psql query failed (exit $rc): $(printf '%s' "$out" | head -c 200)"
    else
      record "spendlogs" WARN "psql query failed; skipping LiteLLM_SpendLogs check: $(printf '%s' "$out" | head -c 200)"
    fi
    return
  fi

  py_check check-spendlogs "$out" --end-user "$SMOKE_TAG" --request-id "$LAST_REQUEST_ID" \
    --window-minutes "${DEEP_SMOKE_SPENDLOGS_WINDOW_MINUTES:-$DEFAULT_SPENDLOGS_WINDOW_MINUTES}"
  record "spendlogs" "$(map_rc_to_status "$CAPTURED_RC")" "$CAPTURED_OUT"
}

run_quick() {
  check_health
  check_ready
  check_version
  check_models
  check_completion
  check_pods
}

run_full() {
  run_quick
  check_responses_shape
  check_messages_shape
  check_stream
  check_provider_families
  check_admin_status
  check_admin_credentials
  check_admin_quota
  check_jobs
  check_spendlogs
}

print_summary() {
  echo
  echo "## Deep Smoke Summary — env=$ENVIRONMENT mode=$MODE tag=$SMOKE_TAG"
  echo
  echo "| Check | Status | Detail |"
  echo "|---|---|---|"
  local i
  for i in "${!CHECK_NAMES[@]}"; do
    printf '| %s | %s | %s |\n' "${CHECK_NAMES[$i]}" "${CHECK_STATUSES[$i]}" "${CHECK_DETAILS[$i]}"
  done
  echo
}

case "$MODE" in
  quick) run_quick ;;
  full) run_full ;;
esac

print_summary

OVERALL="PASS"
for status in "${CHECK_STATUSES[@]}"; do
  case "$status" in
    FAIL) OVERALL="FAIL" ;;
    WARN)
      if [ "$OVERALL" = "PASS" ]; then
        OVERALL="WARN"
      fi
      ;;
  esac
done

echo "Overall: $OVERALL"

if [ "$OVERALL" = "FAIL" ]; then
  exit 1
fi
if [ "$OVERALL" = "WARN" ] && [ "$STRICT" = "1" ]; then
  exit 1
fi
exit 0
