#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
staging_doc="${repo_root}/docs/CICD_PHASE2_STAGING.md"
classifier="$({
  sed -n \
    -e '/^require_permission_denied() {$/,/^}$/p' \
    -e '/^require_denied_with_valid_token() {$/,/^}$/p' \
    "${staging_doc}"
})"
eval "${classifier}"

grep -Fqx 'GATEWAY_ENGINE_OPENBAO_AUTH_MOUNT=kubernetes-k3s-01' "${staging_doc}"
grep -Fqx 'gateway_service_account="gateway-engine-openbao"' "${staging_doc}"
grep -Fqx 'openbao_auth_mount="kubernetes-k3s-01"' "${staging_doc}"

test_path="launcher-keys/policy-check/test"
allowed_read_status=0
bao() {
  if [[ "$*" != "kv get -mount=kv ${test_path}" ]]; then
    echo "ERROR: unexpected bao invocation: $*" >&2
    return 64
  fi
  return "${allowed_read_status}"
}

success() { return 0; }
real_policy_denial() {
  printf '%s\n' 'Code: 403. Errors:' '* permission denied' >&2
  return 2
}
local_permission_denial() {
  printf '%s\n' 'bash: /root/secret: Permission denied' >&2
  return 126
}
tls_failure() {
  printf '%s\n' 'tls: failed to verify certificate' >&2
  return 1
}
transport_failure() {
  printf '%s\n' 'dial tcp: connection refused' >&2
  return 1
}
expired_token() {
  printf '%s\n' 'Code: 403. Errors:' '* permission denied: token expired' >&2
  return 2
}
server_failure() {
  printf '%s\n' 'Code: 503. Errors:' '* permission denied while backend unavailable' >&2
  return 2
}

require_permission_denied "real policy denial" real_policy_denial

allowed_read_status=0
require_denied_with_valid_token "real policy denial with valid token" \
  real_policy_denial

allowed_read_status=2
if require_denied_with_valid_token "generic 403 with failed allowed read" \
  real_policy_denial >/dev/null 2>&1; then
  echo "ERROR: gate accepted a denial after the known-allowed read failed" >&2
  exit 1
fi
allowed_read_status=0

for rejected in \
  success \
  local_permission_denial \
  tls_failure \
  transport_failure \
  expired_token \
  server_failure; do
  if require_permission_denied "${rejected}" "${rejected}" >/dev/null 2>&1; then
    echo "ERROR: classifier accepted ${rejected}" >&2
    exit 1
  fi
done

echo "OpenBao policy-denial classifier matrix passed"
