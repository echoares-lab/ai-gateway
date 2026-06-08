#!/bin/bash
# Pre-commit hook to prevent committing hardcoded API keys in sensitive config/code files

set -e

PLACEHOLDER_RE='sk-changeme|sk-ci-mock|cliproxy-changeme|mock-key|dev-management-key'
API_KEY_RE='api_key:[[:space:]]+[a-zA-Z0-9-]{20,}'
SK_HEX_RE='sk-[0-9a-fA-F]{32,}'
CLIPROXY_RE='cliproxy-[a-zA-Z0-9]{10,}'

SCAN_FILES=(
  litellm-config.yaml
  services/gateway-engine/main.py
  docker-compose.yml
  docker-compose.dev.yml
)

_check_content() {
  local file="$1"
  local content="$2"
  local matches=""

  [ -z "$content" ] && return 0

  api_key_matches=$(
    echo "$content" | grep -En "$API_KEY_RE" | grep -Ev 'os\.environ' || true
  )
  sk_matches=$(
    echo "$content" | grep -En "$SK_HEX_RE" | grep -Ev "$PLACEHOLDER_RE" || true
  )
  cliproxy_matches=$(
    echo "$content" | grep -En "$CLIPROXY_RE" | grep -Ev "$PLACEHOLDER_RE" || true
  )

  matches=$(printf '%s\n%s\n%s\n' "$api_key_matches" "$sk_matches" "$cliproxy_matches" | sed '/^$/d')
  if [ -n "$matches" ]; then
    echo "❌ ERROR: Hardcoded API key detected in ${file}"
    echo "Use os.environ/... or allowed placeholders (sk-changeme, cliproxy-changeme, mock-key, dev-management-key)"
    echo ""
    echo "Matching lines:"
    echo "$matches"
    return 1
  fi
  return 0
}

_scan_file() {
  local file="$1"
  local content=""

  if [ "${CHECK_ALL:-}" = 1 ]; then
    [ -f "$file" ] || return 0
    content=$(cat "$file")
  else
    content=$(
      git diff --cached "$file" 2>/dev/null | grep '^+' | grep -v '^+++' | sed 's/^+//' || true
    )
    [ -z "$content" ] && return 0
  fi

  _check_content "$file" "$content"
}

failed=0
for file in "${SCAN_FILES[@]}"; do
  _scan_file "$file" || failed=1
done
for file in services/credential-prober/*.py; do
  [ -f "$file" ] || continue
  _scan_file "$file" || failed=1
done

[ "$failed" -eq 0 ] || exit 1
[ "${CHECK_ALL:-}" = 1 ] && echo "✓ No hardcoded API keys found"
exit 0
