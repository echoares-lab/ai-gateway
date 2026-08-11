#!/usr/bin/env bash
# OpenBao staging launcher-key escrow policy-denial classifier.
#
# This file is the executable source of truth for the staging escrow gate. It is
# sourced by two consumers:
#
#   * tests/test-openbao-policy-denial-classifier.sh — the offline matrix that
#     proves the classifier rejects transport, TLS, expired-token, and server
#     failures rather than accepting them as policy denials.
#   * The operator escrow gate procedure documented in the vault at
#     01 Projects/AI-Gateway/Specs/CICD_PHASE2_STAGING.md, which sources this
#     file rather than restating the functions in prose.
#
# The staging identity constants below must match the authoritative GitOps
# manifest for the ai-gateway-staging namespace. They are references and routing
# settings, not credentials.
#
# Callers must set `test_path` to a disposable KV path before invoking
# require_denied_with_valid_token, and must provide a `bao` command on PATH.

OPENBAO_STAGING_NAMESPACE="ai-gateway-staging"
OPENBAO_GATEWAY_SERVICE_ACCOUNT="gateway-engine-openbao"
OPENBAO_AUTH_MOUNT="kubernetes-k3s-01"
OPENBAO_WORKLOAD_ROLE="ai-gateway-staging-launcher-keys"

# Fail the probe unless the command produced a genuine OpenBao HTTP 403
# policy denial. A nonzero exit status alone is not sufficient: local shell
# "Permission denied", TLS verification failures, transport errors, expired or
# revoked tokens, and 5xx responses must all be treated as test failures so a
# broken probe is never mistaken for a correctly restrictive policy.
require_permission_denied() {
  local description="$1"
  shift
  local output status

  set +e
  output="$("$@" 2>&1)"
  status=$?
  set -e

  if (( status == 0 )); then
    echo "ERROR: workload policy permits ${description}" >&2
    return 1
  fi
  if ! grep -Eiq '^[[:space:]]*Code:[[:space:]]*403([[:space:].]|$)' <<<"${output}" ||
    ! grep -Eiq 'permission denied' <<<"${output}" ||
    grep -Eiq '(token[^[:alnum:]]*(expired|invalid|revoked)|expired[^[:alnum:]]*token|invalid client token|missing client token)' <<<"${output}"; then
    echo "ERROR: ${description} probe failed without an OpenBao HTTP 403 policy-denied response (status=${status})" >&2
    echo "       Treat transport, TLS, expired-token, and server failures as test failures; diagnose and rerun." >&2
    return 1
  fi
}

require_denied_with_valid_token() {
  local description="$1"
  shift

  require_permission_denied "${description}" "$@"
  # A real policy denial and an expired workload token can both be a generic
  # OpenBao 403. Prove this same token is still usable immediately afterward.
  if ! bao kv get -mount=kv "${test_path}" >/dev/null; then
    echo "ERROR: ${description} was denied, but the known-allowed read also failed" >&2
    echo "       Token validity is unproven; refresh the workload token and rerun." >&2
    return 1
  fi
}
