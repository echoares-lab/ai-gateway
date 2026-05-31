#!/bin/bash
# Pre-commit hook to validate YAML syntax

set -e

# Check if litellm-config.yaml is being staged and validate it
if git diff --cached --name-only | grep -q 'litellm-config.yaml'; then
  echo "Validating litellm-config.yaml syntax..."

  # Create a temporary file with staged changes
  staged_yaml=$(mktemp)
  git show ":litellm-config.yaml" > "$staged_yaml" || true

  # Validate YAML
  if ! python3 -c "import yaml; yaml.safe_load(open('$staged_yaml'))" 2>/dev/null; then
    echo "❌ YAML validation failed for litellm-config.yaml"
    echo "Fix syntax errors before committing"
    rm -f "$staged_yaml"
    exit 1
  fi

  rm -f "$staged_yaml"
  echo "✓ YAML valid"
fi

exit 0
