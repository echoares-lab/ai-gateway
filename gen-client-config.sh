#!/usr/bin/env bash
#
# gen-client-config.sh — print ready-to-paste integration/config snippets for
# AI Gateway client profiles (issue #78, epic #36).
#
# Profiles and their connection details are derived from
# docs/CLIENT_COMPATIBILITY.md §2 (Integration Profiles). This script only PRINTS
# configuration; it never reads secrets, never writes files, and never calls the
# gateway. The API key is always a placeholder the operator substitutes.
#
# Tenant keys use: ak-{org}-{workspace}-{team}-{repo}-{environment} (docs/TENANCY.md).
#
# Usage:
#   ./gen-client-config.sh [client] [--base-url URL] [--key-var NAME]
#       [--org ORG] [--workspace WS] [--team TEAM] [--repo REPO] [--env ENV]
#
#   client      one of: cursor | claude-code | codex | gemini | openai-sdk | all
#               (default: all)
#   --base-url  gateway base URL (default: http://localhost:4000)
#   --key-var   env var name to reference for the key (default: AI_GATEWAY_KEY)
#   --org/--workspace/--team/--repo/--env  build example ak-… key label in header
#
# Examples:
#   ./gen-client-config.sh cursor
#   ./gen-client-config.sh all --base-url http://localhost:4000
#   ./gen-client-config.sh gemini --org echoares --workspace core --team eng --repo my-app

set -euo pipefail

BASE_URL="http://localhost:4000"
KEY_VAR="AI_GATEWAY_KEY"
CLIENT="all"
TENANT_ORG="echoares"
TENANT_WORKSPACE="core"
TENANT_TEAM="eng"
TENANT_REPO="my-repo"
TENANT_ENV="dev"

while [ $# -gt 0 ]; do
  case "$1" in
    --base-url)
      BASE_URL="${2:?--base-url requires a value}"
      shift 2
      ;;
    --key-var)
      KEY_VAR="${2:?--key-var requires a value}"
      shift 2
      ;;
    --org)
      TENANT_ORG="${2:?--org requires a value}"
      shift 2
      ;;
    --workspace)
      TENANT_WORKSPACE="${2:?--workspace requires a value}"
      shift 2
      ;;
    --team)
      TENANT_TEAM="${2:?--team requires a value}"
      shift 2
      ;;
    --repo)
      TENANT_REPO="${2:?--repo requires a value}"
      shift 2
      ;;
    --env)
      TENANT_ENV="${2:?--env requires a value}"
      shift 2
      ;;
    -h | --help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    cursor | claude-code | codex | gemini | openai-sdk | all)
      CLIENT="$1"
      shift
      ;;
    *)
      echo "error: unknown argument '$1' (try --help)" >&2
      exit 2
      ;;
  esac
done

# Normalise: strip a trailing slash and any trailing /v1 so we can compose paths.
BASE_URL="${BASE_URL%/}"
BASE_ROOT="${BASE_URL%/v1}"
KEY_REF="\${${KEY_VAR}}"
TENANT_KEY_EXAMPLE="ak-${TENANT_ORG}-${TENANT_WORKSPACE}-${TENANT_TEAM}-${TENANT_REPO}-${TENANT_ENV}"

_hr() { printf '─%.0s' $(seq 1 70); echo; }

gen_cursor() {
  _hr
  echo "Cursor  (Settings → Models → OpenAI API)"
  _hr
  cat <<EOF
Base URL:    ${BASE_ROOT}/v1
API Key:     ${KEY_REF}        # LiteLLM key; label should match ${TENANT_KEY_EXAMPLE}
Model name:  AI-Gateway:claude-sonnet-4-6   # the AI-Gateway: prefix is required

Notes:
  - Cursor sees models from GET ${BASE_ROOT}/v1/models (prefixed with "AI-Gateway:").
  - The gateway-engine strips the prefix before forwarding to LiteLLM.
  - Tenant metadata is extracted when the Bearer token starts with ak- (see docs/TENANCY.md).
EOF
  echo
}

gen_claude_code() {
  _hr
  echo "Claude Code / Claude CLI"
  _hr
  cat <<EOF
export ANTHROPIC_BASE_URL="${BASE_ROOT}"
export ANTHROPIC_API_KEY="${KEY_REF}"   # Bearer ${TENANT_KEY_EXAMPLE} or mapped team key
# Then use a gateway model alias, e.g.:
#   claude --model claude-sonnet-4-6
EOF
  echo
}

gen_codex() {
  _hr
  echo "Codex CLI  (~/.codex/config.toml)"
  _hr
  cat <<EOF
openai_base_url = "${BASE_ROOT}/v1"
# Auth: Authorization: Bearer ${KEY_REF}  (tenant label: ${TENANT_KEY_EXAMPLE})
# Codex uses the Responses API endpoint: ${BASE_ROOT}/v1/responses
# Non-OpenAI models on /v1/responses/compact are rewritten to gpt-5-5 automatically.
EOF
  echo
}

gen_gemini() {
  _hr
  echo "Gemini CLI"
  _hr
  cat <<EOF
export GEMINI_BASE_URL="${BASE_ROOT}/v1beta"
export GEMINI_API_KEY="${KEY_REF}"   # Bearer ${TENANT_KEY_EXAMPLE} when using gateway keys
# Endpoint shape: ${BASE_ROOT}/v1beta/models/<model>:generateContent
EOF
  echo
}

gen_openai_sdk() {
  _hr
  echo "Generic OpenAI SDK (Python)"
  _hr
  cat <<EOF
from openai import OpenAI

client = OpenAI(
    base_url="${BASE_ROOT}/v1",
    api_key="${KEY_REF}",   # LiteLLM virtual key (${TENANT_KEY_EXAMPLE})
)
resp = client.chat.completions.create(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "ping"}],
)
print(resp.choices[0].message.content)
EOF
  echo
}

echo "# AI Gateway client config — base: ${BASE_ROOT}  key var: ${KEY_VAR}"
echo "# Example tenant key label: ${TENANT_KEY_EXAMPLE}  (docs/TENANCY.md, setup-repo-env.sh)"
echo "# (placeholders only; substitute your own key. See docs/CLIENT_COMPATIBILITY.md)"
echo

case "$CLIENT" in
  cursor) gen_cursor ;;
  claude-code) gen_claude_code ;;
  codex) gen_codex ;;
  gemini) gen_gemini ;;
  openai-sdk) gen_openai_sdk ;;
  all)
    gen_cursor
    gen_claude_code
    gen_codex
    gen_gemini
    gen_openai_sdk
    ;;
esac
