#!/usr/bin/env bash
# Re-register and start the ai-gateway self-hosted runner (dev-01).
# Requires: sudo, gh auth with repo admin, runner host access.
set -euo pipefail

RUNNER_ROOT="${RUNNER_ROOT:-/home/github-runner/actions-runner}"
RUNNER_USER="${RUNNER_USER:-github-runner}"
RUNNER_NAME="${RUNNER_NAME:-dev-01}"
REPO_URL="${REPO_URL:-https://github.com/echoares-lab/ai-gateway}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Re-run with sudo: sudo $0" >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI required to fetch registration token" >&2
  exit 1
fi

TOKEN="$(gh api "repos/echoares-lab/ai-gateway/actions/runners/registration-token" -X POST --jq .token)"
if [[ -z "$TOKEN" ]]; then
  echo "Failed to obtain registration token" >&2
  exit 1
fi

mkdir -p /var/cache/ai-gateway/{pip,buildkit}
chown -R "${RUNNER_USER}:${RUNNER_USER}" /var/cache/ai-gateway

if [[ ! -f /etc/sudoers.d/github-runner ]]; then
  echo "${RUNNER_USER} ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/github-runner
  chmod 440 /etc/sudoers.d/github-runner
  visudo -cf /etc/sudoers.d/github-runner
fi

sudo -u "$RUNNER_USER" bash -c "
  cd '$RUNNER_ROOT' && ./config.sh \
    --url '$REPO_URL' \
    --token '$TOKEN' \
    --name '$RUNNER_NAME' \
    --work _work \
    --labels self-hosted,Linux,X64,ci \
    --unattended \
    --replace
"

cd "$RUNNER_ROOT"
if ! ./svc.sh status 2>/dev/null | grep -q 'active (running)'; then
  ./svc.sh install "$RUNNER_USER" || true
  ./svc.sh start
fi
./svc.sh status

echo ""
echo "Runner re-registered. Verify with: scripts/ci-runner-status.sh"
