#!/bin/bash
# Pre-commit hook to prevent committing hardcoded API keys to litellm-config.yaml

set -e

# Check for hardcoded API keys in litellm-config.yaml
if git diff --cached litellm-config.yaml 2>/dev/null | grep -E '^\+.*api_key: [a-zA-Z0-9-]{20,}(?!.*os\.environ)' >/dev/null 2>&1; then
  echo "❌ ERROR: Hardcoded API key detected in litellm-config.yaml"
  echo "Use 'api_key: os.environ/CLIPROXY_API_KEY' instead of literal key values"
  echo ""
  echo "Staged changes with hardcoded keys:"
  git diff --cached litellm-config.yaml | grep -E '^\+.*api_key:'
  exit 1
fi

exit 0
