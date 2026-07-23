#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
classifier="$({
  sed -n '/^require_permission_denied() {$/,/^}$/p' \
    "${repo_root}/docs/CICD_PHASE2_STAGING.md"
})"
eval "${classifier}"

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
