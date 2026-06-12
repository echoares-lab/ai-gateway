#!/usr/bin/env bash
# Quick health check for the self-hosted GitHub Actions runner on dev-01.
set -euo pipefail

RUNNER_ROOT="${RUNNER_ROOT:-/home/github-runner/actions-runner}"
SERVICE="actions.runner.echoares-lab-ai-gateway.dev-01.service"

echo "── systemd ──"
systemctl is-active "$SERVICE" 2>/dev/null || echo "service not active"
systemctl is-enabled "$SERVICE" 2>/dev/null || true

echo ""
echo "── runner config ──"
if [[ -f "$RUNNER_ROOT/.runner" ]]; then
  echo "configured: yes ($RUNNER_ROOT/.runner)"
else
  echo "configured: NO — run scripts/ci-runner-reregister.sh"
fi

echo ""
echo "── cache dirs ──"
ls -ld /var/cache/ai-gateway /var/cache/ai-gateway/pip /var/cache/ai-gateway/buildkit 2>/dev/null || echo "cache dirs missing"

echo ""
echo "── GitHub API (repo runners) ──"
if command -v gh >/dev/null 2>&1; then
  gh api repos/echoares-lab/ai-gateway/actions/runners \
    --jq '.runners[] | "\(.name): \(.status) busy=\(.busy) labels=\([.labels[].name] | join(","))"' \
    2>/dev/null || echo "(gh api failed — check auth)"
else
  echo "gh CLI not installed"
fi
