#!/usr/bin/env bash
# Push rotated gateway credentials to 1Password.
# Auth: set -a && source ~/.op-token && set +a   OR   eval "$(op signin)"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PAYLOAD="${ROOT}/.rotate-secrets-op.env"
VAULT="${OP_VAULT:-ai-gateway}"
ITEM="${OP_ITEM:-dev-secrets}"

if [[ -f "${HOME}/.op-token" && -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${HOME}/.op-token"
  set +a
fi

if ! op whoami >/dev/null 2>&1; then
  echo "ERROR: 1Password CLI not signed in."
  echo "  Service account: set -a && source ~/.op-token && set +a"
  echo "  Personal account: eval \"\$(op signin)\""
  exit 1
fi

if [[ ! -f "$PAYLOAD" ]]; then
  echo "ERROR: missing $PAYLOAD — run credential rotation first or set vars in .env"
  exit 1
fi

# shellcheck disable=SC1090
source "$PAYLOAD"

for field in LITELLM_MASTER_KEY CLIPROXY_API_KEY CLIPROXY_MANAGEMENT_KEY; do
  val="${!field:-}"
  if [[ -z "$val" ]]; then
    echo "ERROR: $field empty in $PAYLOAD"
    exit 1
  fi
  echo "Updating op://${VAULT}/${ITEM}/${field} ..."
  op item edit "$ITEM" --vault "$VAULT" "${field}[password]=${val}" >/dev/null
done

echo "✓ 1Password item '${ITEM}' updated in vault '${VAULT}'"
echo "  Remove payload when done: rm -f ${PAYLOAD}"
