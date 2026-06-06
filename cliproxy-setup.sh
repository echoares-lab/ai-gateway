#!/usr/bin/env bash
# CLIProxyAPI setup and management script
# Wraps Claude Pro, ChatGPT Plus/Codex, and Gemini CLI as a Docker-managed OpenAI-compatible API
# LiteLLM talks to the cliproxy container via Docker network: http://cliproxy:8317
#
# WARNING: Using consumer subscriptions via automated relay may violate provider ToS.
# Intended for personal local use only.

set -euo pipefail

CLIPROXY_PORT=8317
CLIPROXY_DIR="$HOME/.cliproxy"
CLIPROXY_BIN="$CLIPROXY_DIR/cli-proxy-api"
CLIPROXY_CONFIG="$CLIPROXY_DIR/config.yaml"
CLIPROXY_REPO="router-for-me/CLIProxyAPI"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LITELLM_CONFIG="${LITELLM_CONFIG:-$SCRIPT_DIR/litellm-config.yaml}"
LITELLM_KEY="${LITELLM_MASTER_KEY:-$(grep '^LITELLM_MASTER_KEY=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2 || true)}"
TRANSLATOR_URL="${TRANSLATOR_URL:-http://localhost:${TRANSLATOR_PORT:-4000}}"

# Detect OS/arch for binary download
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  ARCH="amd64" ;;
  aarch64) ARCH="aarch64" ;;
  arm64)   ARCH="aarch64" ;;
esac

# ──────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────

validate_yaml() {
  # Validate YAML syntax
  local yaml_file="${1:-$LITELLM_CONFIG}"
  if ! python3 -c "import yaml, sys; yaml.safe_load(open('$yaml_file'))" 2>/dev/null; then
    echo "❌ YAML validation failed for $yaml_file"
    return 1
  fi
  return 0
}

write_config() {
  if [ -f "$CLIPROXY_CONFIG" ]; then return; fi
  local apikey
  apikey="cliproxy-$(head -c 16 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
  mkdir -p "$CLIPROXY_DIR"
  cat > "$CLIPROXY_CONFIG" <<EOF
port: $CLIPROXY_PORT
host: ""
auth-dir: "$HOME/.cli-proxy-api"
api-keys:
  - "$apikey"
debug: false

# Usage statistics — required for cpa-manager analytics dashboard
usage-statistics-enabled: true
redis-usage-queue-retention-seconds: 60  # how long usage events stay in Redis queue

# Quota handling — fall back to Antigravity credits when quota exceeded
quota-exceeded:
  antigravity-credits: true

# Streaming reliability — prevents idle timeouts on slow models (Opus, Gemini Pro)
streaming:
  keepalive-seconds: 30      # send SSE keep-alive every 30s during long requests
  bootstrap-retries: 2       # retry N times before first byte on transient failures
EOF
  echo "Config written to $CLIPROXY_CONFIG"
  echo "CLIProxyAPI API key: $apikey"
}

get_api_key() {
  if [ -n "${CLIPROXY_API_KEY:-}" ]; then
    echo "$CLIPROXY_API_KEY"
    return
  fi
  local from_env
  from_env=$(grep '^CLIPROXY_API_KEY=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2-)
  if [ -n "$from_env" ]; then
    echo "$from_env"
    return
  fi
  grep -A2 'api-keys:' "$CLIPROXY_CONFIG" 2>/dev/null | grep '^\s*-' | sed -E 's/^\s*-\s*//' | sed -E 's/^"([^"]*)".*/\1/' | head -1
}

get_mgmt_key() {
  # Try env var first, then .env file, then config.yaml management-key field
  if [ -n "${CLIPROXY_MANAGEMENT_KEY:-}" ]; then
    echo "$CLIPROXY_MANAGEMENT_KEY"
    return
  fi
  local from_env
  from_env=$(grep '^CLIPROXY_MANAGEMENT_KEY=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2)
  if [ -n "$from_env" ]; then
    echo "$from_env"
    return
  fi
  grep 'management-key:' "$CLIPROXY_CONFIG" 2>/dev/null | sed 's/.*management-key:\s*//' | tr -d '"' | head -1
}

get_translator_admin_key() {
  if [ -n "${TRANSLATOR_ADMIN_KEY:-}" ]; then
    echo "$TRANSLATOR_ADMIN_KEY"
    return
  fi
  grep '^TRANSLATOR_ADMIN_KEY=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2- || true
}

cmd_quota_summary() {
  local mgmt_key
  mgmt_key=$(get_mgmt_key)
  if [ -z "$mgmt_key" ]; then
    echo "ERROR: management key not found. Set CLIPROXY_MANAGEMENT_KEY in .env or ~/.cliproxy/config.yaml"
    exit 1
  fi

  local raw
  raw=$(curl -sf "http://localhost:$CLIPROXY_PORT/v0/management/auth-files" \
    -H "X-Management-Key: $mgmt_key" 2>/dev/null) || {
    echo "ERROR: CLIProxy management API not reachable on port $CLIPROXY_PORT"
    exit 1
  }

  echo "=== Per-credential quota summary ==="
  CLIPROXY_QUOTA_RAW="$raw" python3 - <<'PYEOF'
import os, json, sys

data = json.loads(os.environ["CLIPROXY_QUOTA_RAW"])
files = data.get("files", [])
if not files:
    print("  (no credentials found)")
    sys.exit(0)

# Group by provider
by_provider = {}
for f in files:
    p = f.get("provider", "?")
    by_provider.setdefault(p, []).append(f)

for provider, creds in sorted(by_provider.items()):
    print(f"\n  [{provider}]")
    for c in creds:
        email      = c.get("email", c.get("account", "?"))
        disabled   = c.get("disabled", False)
        last_ref   = (c.get("last_refresh") or "-")[:19]
        recent     = c.get("recent_requests", [])
        success    = sum(r.get("success", 0) for r in recent)
        failed     = sum(r.get("failed", 0) for r in recent)
        status     = "DISABLED" if disabled else "active"
        print(f"    {email:<45}  {status:<8}  last_refresh={last_ref}  "
              f"recent: ok={success} err={failed}")
PYEOF
}

require_bin() {
  if [ ! -x "$CLIPROXY_BIN" ]; then
    echo "CLIProxyAPI binary not found at $CLIPROXY_BIN"
    echo "Run: $0 install"
    exit 1
  fi
  write_config
}

# Convert CLIProxyAPI model ID to a LiteLLM-safe alias (dots → dashes)
model_to_alias() { echo "$1" | tr '.' '-'; }

GEMINI_MAP_FILE="${GEMINI_MAP_FILE:-$SCRIPT_DIR/services/translator/gemini-model-map.json}"

# Add a dotted→dashed entry to gemini-model-map.json (no-op if key == value or not Gemini)
gemini_map_add() {
  local model_id="$1" alias="$2"
  [[ "$model_id" != gemini-* ]] && return
  [[ "$model_id" == "$alias" ]] && return
  python3 - "$GEMINI_MAP_FILE" "$model_id" "$alias" <<'PYEOF'
import sys, json, os
path, model_id, alias = sys.argv[1:]
data = {}
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
data[model_id] = alias
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
PYEOF
}

# Remove an entry from gemini-model-map.json by its dashed alias (no-op if not Gemini)
gemini_map_remove() {
  local alias="$1"
  [[ "$alias" != gemini-* ]] && return
  python3 - "$GEMINI_MAP_FILE" "$alias" <<'PYEOF'
import sys, json, os
path, alias = sys.argv[1:]
if not os.path.exists(path):
    sys.exit(0)
with open(path) as f:
    data = json.load(f)
data = {k: v for k, v in data.items() if v != alias}
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
PYEOF
}

# Check if a model alias already exists in litellm-config.yaml
alias_in_config() {
  grep -q "model_name: $1" "$LITELLM_CONFIG" 2>/dev/null
}

# Probe a model via CLIProxyAPI; return status code (0 = success, 429/503 = rate/unavail, other = error)
# Returns: 0 (success), 429 (rate limit), 503 (unavailable), other HTTP code, or -1 (network error)
probe_model() {
  local model="$1"
  local api_key
  api_key=$(get_api_key)

  # Capture HTTP status code
  local http_code
  local result
  result=$(curl -s --max-time 20 -w "\n%{http_code}" -X POST "http://localhost:$CLIPROXY_PORT/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $api_key" \
    -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":3}" 2>/dev/null)

  http_code=$(echo "$result" | tail -1)
  PROBE_HTTP_CODE="$http_code"
  local body=$(echo "$result" | head -n -1)

  # Check if HTTP code was successful
  if [ "$http_code" = "200" ]; then
    # Verify response has choices array
    if echo "$body" | python3 -c "import sys,json; r=json.load(sys.stdin); exit(0 if r.get('choices') else 1)" 2>/dev/null; then
      return 0  # Success
    else
      return 1  # Invalid response
    fi
  else
    # Return mapped values so they fit in 0-255 range and don't exit script under set -e
    if [ "$http_code" = "429" ]; then
      return 42
    elif [ "$http_code" = "503" ]; then
      return 53
    else
      return 99
    fi
  fi
}

# ──────────────────────────────────────────────
# Cost / feature metadata helpers
# ──────────────────────────────────────────────

# Query the LiteLLM container's model registry for cost and feature data for
# every openai/ model currently in LITELLM_CONFIG. Writes JSON to a temp file
# and prints the file path. Caller must rm the file when done.
# Outputs '{}' if the container is unreachable or no openai/ models are found.
fetch_config_model_costs() {
  local model_ids
  model_ids=$(grep -E '^\s+model: openai/' "$LITELLM_CONFIG" \
    | sed 's/.*openai\///' | sort -u | tr '\n' ' ')

  local costs_file
  costs_file=$(mktemp)

  if [ -z "${model_ids// }" ]; then
    echo '{}' > "$costs_file"
    echo "$costs_file"
    return
  fi

  local tmp_out
  tmp_out=$(mktemp)
  # Unquoted intentionally: word-splits model IDs into separate argv entries.
  # Stdout captured to file because litellm writes ANSI startup messages at the
  # OS fd level — sys.stdout redirection cannot suppress them.
  # shellcheck disable=SC2086
  docker compose -f "$SCRIPT_DIR/docker-compose.yml" exec -T litellm \
    python3 - $model_ids >"$tmp_out" 2>/dev/null <<'PYEOF' || true
import litellm, json, sys

FIELDS = [
    'input_cost_per_token', 'output_cost_per_token',
    'cache_creation_input_token_cost', 'cache_read_input_token_cost',
    'max_input_tokens', 'max_output_tokens',
    'supports_prompt_caching', 'supports_vision', 'supports_function_calling',
]
result = {}
for model in sys.argv[1:]:
    for candidate in [model, 'anthropic/' + model, 'gemini/' + model]:
        try:
            info = litellm.get_model_info(candidate)
            if info and info.get('input_cost_per_token') is not None:
                result[model] = {k: info[k] for k in FIELDS if info.get(k) is not None}
                break
        except Exception:
            pass
    if model not in result:
        result[model] = {}
print('__COSTS__:' + json.dumps(result))
PYEOF
  # Use sentinel prefix to extract our line from litellm's noisy stdout.
  # Write directly to file — avoids bash variable corruption of large JSON.
  if grep -q '^__COSTS__:' "$tmp_out" 2>/dev/null; then
    grep '^__COSTS__:' "$tmp_out" | tail -1 | sed 's/^__COSTS__://' > "$costs_file"
  else
    echo '{}' > "$costs_file"
  fi
  rm -f "$tmp_out"
  echo "$costs_file"
}

# Add or merge model_info blocks into LITELLM_CONFIG for all openai/ entries
# that lack a base_model field. Preserves existing fields such as
# disable_background_health_check. Prints "changed" or "no_change".
apply_model_info() {
  local costs_file="$1"
  python3 - "$LITELLM_CONFIG" "$costs_file" <<'PYEOF'
import sys, json, re

path, costs_file = sys.argv[1], sys.argv[2]
with open(costs_file) as f:
    costs = json.load(f)

COST_FIELDS = ['input_cost_per_token', 'output_cost_per_token',
               'cache_creation_input_token_cost', 'cache_read_input_token_cost']
INT_FIELDS  = ['max_input_tokens', 'max_output_tokens']
BOOL_FIELDS = ['supports_prompt_caching', 'supports_vision', 'supports_function_calling']

def sci(v): return f'{float(v):.2e}'

def build_info_lines(model_id, cost_data):
    out = [f'      base_model: {model_id}']
    for f in COST_FIELDS:
        if cost_data.get(f) is not None:
            out.append(f'      {f}: {sci(cost_data[f])}')
    for f in INT_FIELDS:
        if cost_data.get(f) is not None:
            out.append(f'      {f}: {int(cost_data[f])}')
    for f in BOOL_FIELDS:
        if cost_data.get(f) is not None:
            out.append(f'      {f}: {"true" if cost_data[f] else "false"}')
    return [l + '\n' for l in out]

with open(path) as f:
    lines = f.readlines()

out = []
i = 0
changed = False

while i < len(lines):
    line = lines[i]
    if re.match(r'  - model_name: \S', line):
        entry = [line]
        i += 1
        while i < len(lines) and (lines[i].startswith('    ') or lines[i].strip() == ''):
            entry.append(lines[i])
            i += 1

        entry_text = ''.join(entry)
        m = re.search(r'model: openai/(\S+)', entry_text)

        if not m or 'base_model:' in entry_text:
            out.extend(entry)
            continue

        model_id = m.group(1)
        new_lines = build_info_lines(model_id, costs.get(model_id, {}))

        if any(l.rstrip() == '    model_info:' for l in entry):
            merged = []
            for el in entry:
                merged.append(el)
                if el.rstrip() == '    model_info:':
                    merged.extend(new_lines)
            out.extend(merged)
        else:
            last_lp = max(
                (j for j, el in enumerate(entry)
                 if el.startswith('      ') and not el.strip().startswith('#')),
                default=None
            )
            if last_lp is not None:
                mi = ['    model_info:\n'] + new_lines
                out.extend(entry[:last_lp + 1] + mi + entry[last_lp + 1:])
            else:
                out.extend(entry)
                continue

        changed = True
    else:
        out.append(line)
        i += 1

with open(path, 'w') as f:
    f.writelines(out)

print('changed' if changed else 'no_change')
PYEOF
}

# Dynamically generate and write appropriate litellm fallbacks to litellm-config.yaml
apply_fallbacks() {
  python3 - "$LITELLM_CONFIG" <<'PYEOF'
import sys, re

path = sys.argv[1]
with open(path) as f:
    txt = f.read()

# Let's find all model names defined in the model_list section.
models = []
for line in txt.splitlines():
    m = re.match(r'^  - model_name:\s*(\S+)', line)
    if m:
        models.append(m.group(1))

# Generate fallback targets based on prefix rules
fallbacks_list = []
for model in sorted(models):
    # Rule matching
    if 'claude-opus' in model:
        # e.g., claude-opus-4-8 falls back to gpt-5-5, gemini-3-1-pro
        fallbacks_list.append({model: ["gpt-5-5", "gemini-3-1-pro"]})
    elif 'claude-sonnet' in model:
        fallbacks_list.append({model: ["gpt-5-4", "gemini-3-flash"]})
    elif 'claude-haiku' in model:
        fallbacks_list.append({model: ["gpt-5-4-mini", "gemini-3-flash"]})
    elif 'gpt-5-4-mini' in model:
        fallbacks_list.append({model: ["claude-haiku-4-5", "gemini-3-flash"]})
    elif 'gpt-5-4' in model:
        fallbacks_list.append({model: ["claude-sonnet-4-6", "gemini-3-flash"]})
    elif 'gpt-5-5' in model:
        fallbacks_list.append({model: ["claude-opus-4-7", "gemini-3-1-pro"]})
    elif 'gemini-3-1-pro' in model or 'gemini-3-pro' in model or 'gemini-2-5-pro' in model:
        fallbacks_list.append({model: ["claude-sonnet-4-6", "gpt-5-4"]})
    elif 'gemini-2-5-flash' in model or 'gemini-3-flash' in model:
        fallbacks_list.append({model: ["claude-haiku-4-5", "gpt-5-4-mini"]})

# Format fallbacks as a list of YAML maps
formatted_lines = ["  fallbacks:\n"]
for f in fallbacks_list:
    model, targets = list(f.items())[0]
    targets_str = ", ".join(f'"{t}"' for t in targets)
    formatted_lines.append(f'    - {model}: [{targets_str}]\n')

# Now replace the fallbacks: block inside the litellm_settings block of litellm-config.yaml
# Safe regex to replace fallbacks block up to cache or other litellm_settings keys
fallbacks_block_pattern = re.compile(r'  fallbacks:\n.*?(?=\n  \S+:)', re.DOTALL)
new_fallbacks_block = "".join(formatted_lines)

if fallbacks_block_pattern.search(txt):
    new_txt = fallbacks_block_pattern.sub(new_fallbacks_block, txt)
    if new_txt != txt:
        with open(path, 'w') as f:
            f.write(new_txt)
        print("fallbacks_updated")
    else:
        print("no_change")
else:
    print("fallbacks_section_not_found")
PYEOF
}


# ──────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────

cmd_install() {
  echo "Fetching latest CLIProxyAPI release info..."
  local release_json tag version tarball download_url
  release_json=$(curl -fsSL "https://api.github.com/repos/${CLIPROXY_REPO}/releases/latest")
  tag=$(echo "$release_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")
  version="${tag#v}"
  tarball="CLIProxyAPI_${version}_${OS}_${ARCH}.tar.gz"
  download_url="https://github.com/${CLIPROXY_REPO}/releases/download/${tag}/${tarball}"

  echo "Downloading CLIProxyAPI ${tag} for ${OS}/${ARCH}..."
  mkdir -p "$CLIPROXY_DIR"
  local tmp_tar="$CLIPROXY_DIR/${tarball}"
  curl -fsSL "$download_url" -o "$tmp_tar"
  tar -xzf "$tmp_tar" -C "$CLIPROXY_DIR" cli-proxy-api
  rm -f "$tmp_tar"
  chmod +x "$CLIPROXY_BIN"
  echo "Installed: $CLIPROXY_BIN (${tag})"
  write_config
}

cmd_upgrade() {
  echo "Checking for CLIProxyAPI updates..."
  local release_json latest_tag installed_version
  release_json=$(curl -fsSL "https://api.github.com/repos/${CLIPROXY_REPO}/releases/latest")
  latest_tag=$(echo "$release_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")
  latest_version="${latest_tag#v}"

  if [ -x "$CLIPROXY_BIN" ]; then
    installed_version=$("$CLIPROXY_BIN" --version 2>&1 | grep -oP 'Version: \K[^\s,]+' || echo "unknown")
    echo "Installed: $installed_version  Latest: $latest_version"
    if [ "$installed_version" = "$latest_version" ]; then
      echo "Already up to date."
      # Still rebuild Docker image to pick up any OS layer updates
      echo "Rebuilding Docker image..."
      docker compose -f "$SCRIPT_DIR/docker-compose.yml" build \
        --build-arg "CLIPROXY_VERSION=$latest_version" cliproxy
      docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d cliproxy
      return
    fi
  fi

  echo "Upgrading to $latest_version..."
  local tarball="CLIProxyAPI_${latest_version}_${OS}_${ARCH}.tar.gz"
  local download_url="https://github.com/${CLIPROXY_REPO}/releases/download/${latest_tag}/${tarball}"
  local tmp_tar="$CLIPROXY_DIR/${tarball}"
  curl -fsSL "$download_url" -o "$tmp_tar"
  tar -xzf "$tmp_tar" -C "$CLIPROXY_DIR" cli-proxy-api
  rm -f "$tmp_tar"
  chmod +x "$CLIPROXY_BIN"
  echo "Binary upgraded to $latest_version"

  echo "Rebuilding Docker image..."
  docker compose -f "$SCRIPT_DIR/docker-compose.yml" build \
    --build-arg "CLIPROXY_VERSION=$latest_version" cliproxy
  docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d cliproxy
  echo "Done. Run: $0 health"
}

translator_admin_post() {
  local endpoint="$1"
  local body="$2"
  local output_file="$3"
  local admin_key
  admin_key=$(get_translator_admin_key)
  if [ -z "$admin_key" ]; then
    echo "ERROR: TRANSLATOR_ADMIN_KEY is required for sync-models apply mode."
    echo "Set TRANSLATOR_ADMIN_KEY in .env or use: $0 sync-models --legacy"
    return 1
  fi

  curl -fsS -X POST "$TRANSLATOR_URL$endpoint" \
    -H "Content-Type: application/json" \
    -H "x-admin-key: $admin_key" \
    -d "$body" \
    -o "$output_file"
}

translator_admin_patch() {
  local endpoint="$1"
  local body="$2"
  local admin_key
  admin_key=$(get_translator_admin_key)
  curl -fsS -X PATCH "$TRANSLATOR_URL$endpoint" \
    -H "Content-Type: application/json" \
    -H "x-admin-key: $admin_key" \
    -d "$body" >/dev/null
}

summarize_model_sync_response() {
  local response_file="$1"
  python3 - "$response_file" <<'PYEOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    body = json.load(handle)

print(f"  Source: {body.get('source', '-')}")
print(f"  Imported: {body.get('imported_count', 0)}")
diffs = body.get("diffs") or []
if diffs:
    by_kind = {}
    for diff in diffs:
        by_kind[diff.get("kind", "unknown")] = by_kind.get(diff.get("kind", "unknown"), 0) + 1
    print("  Diffs: " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
else:
    print("  Diffs: none")

errors = body.get("errors") or []
if errors:
    print("  Errors:")
    for err in errors:
        print(f"    - {err.get('code', 'error')}: {err.get('message', err)}")
    sys.exit(1)
PYEOF
}

extract_synced_model_ids() {
  local response_file="$1"
  python3 - "$response_file" <<'PYEOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    body = json.load(handle)
for model in body.get("models") or []:
    model_id = model.get("model_id")
    if model_id:
        print(model_id)
PYEOF
}

probe_translator_registry_models() {
  local sync_response_file="$1"
  local admin_key
  admin_key=$(get_translator_admin_key)

  echo ""
  echo "Probing registry models through translator..."
  local probed=0 disabled=0 transient=0 failed=0
  while IFS= read -r model_id; do
    [ -n "$model_id" ] || continue
    probed=$((probed + 1))
    local probe_file
    probe_file=$(mktemp)
    if ! curl -fsS -X POST "$TRANSLATOR_URL/admin/models/$model_id/probe" \
      -H "Content-Type: application/json" \
      -H "x-admin-key: $admin_key" \
      -d '{}' \
      -o "$probe_file"; then
      echo "  WARN $model_id probe request failed"
      failed=$((failed + 1))
      rm -f "$probe_file"
      continue
    fi

    local probe_status
    probe_status=$(python3 - "$probe_file" <<'PYEOF'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle).get("probe_status", "unknown"))
PYEOF
)
    rm -f "$probe_file"

    case "$probe_status" in
      success)
        echo "  OK   $model_id"
        ;;
      rate_limited|temporarily_unavailable|timeout)
        echo "  WARN $model_id $probe_status; keeping enabled"
        transient=$((transient + 1))
        ;;
      missing_model|malformed_response|error)
        echo "  DEAD $model_id $probe_status; disabling in registry"
        if translator_admin_patch "/admin/models/$model_id" '{"enabled":false,"status":"UNAVAILABLE","source":"sync-models"}'; then
          disabled=$((disabled + 1))
        else
          failed=$((failed + 1))
        fi
        ;;
      *)
        echo "  WARN $model_id $probe_status; keeping enabled"
        transient=$((transient + 1))
        ;;
    esac
  done < <(extract_synced_model_ids "$sync_response_file")
  echo "  Probe summary: probed=$probed disabled=$disabled transient=$transient failed=$failed"
}

apply_reconcile_response() {
  local response_file="$1"
  python3 - "$response_file" "$LITELLM_CONFIG" "$GEMINI_MAP_FILE" <<'PYEOF'
import json
import os
import sys
import tempfile

import yaml

response_path, litellm_path, gemini_path = sys.argv[1:]
with open(response_path, encoding="utf-8") as handle:
    body = json.load(handle)

errors = body.get("errors") or []
if errors:
    print("  Reconcile errors:")
    for err in errors:
        print(f"    - {err.get('code', 'error')}: {err.get('message', err)}")
    sys.exit(1)

resources = {item.get("name"): item for item in body.get("resources") or []}
targets = {
    "litellm-config.yaml": litellm_path,
    "gemini-model-map.json": gemini_path,
}

changed = []
for name, path in targets.items():
    resource = resources.get(name)
    if not resource:
        print(f"  Missing reconcile resource: {name}")
        sys.exit(1)
    content = resource.get("content", "")
    if name.endswith(".yaml"):
        yaml.safe_load(content)
    else:
        json.loads(content)
    if not resource.get("changed", False):
        continue
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", dir=directory)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp_path, path)
    changed.append(name)

if changed:
    print("changed:" + ",".join(changed))
else:
    print("no_change")
PYEOF
}

cmd_sync_models_registry() {
  local sync_response reconcile_response apply_result
  sync_response=$(mktemp)
  reconcile_response=$(mktemp)

  echo "Syncing CLIProxy models into translator registry..."
  if ! translator_admin_post "/admin/models/sync" '{"dry_run":false,"source":"cliproxy"}' "$sync_response"; then
    echo "ERROR: translator registry sync failed at $TRANSLATOR_URL."
    echo "Use the explicit emergency path if needed: $0 sync-models --legacy"
    rm -f "$sync_response" "$reconcile_response"
    return 1
  fi
  if ! summarize_model_sync_response "$sync_response"; then
    rm -f "$sync_response" "$reconcile_response"
    return 1
  fi

  if [ "${CLIPROXY_SYNC_PROBE:-true}" != "false" ]; then
    probe_translator_registry_models "$sync_response"
  else
    echo ""
    echo "Skipping model probes because CLIPROXY_SYNC_PROBE=false."
  fi

  echo ""
  echo "Reconciling LiteLLM and Gemini config from translator registry..."
  if ! translator_admin_post "/admin/models/reconcile" '{"dry_run":true,"include_disabled":false}' "$reconcile_response"; then
    echo "ERROR: translator reconcile failed at $TRANSLATOR_URL."
    rm -f "$sync_response" "$reconcile_response"
    return 1
  fi
  if ! apply_result=$(apply_reconcile_response "$reconcile_response"); then
    echo "$apply_result"
    rm -f "$sync_response" "$reconcile_response"
    return 1
  fi
  echo "  $apply_result"

  if [[ "$apply_result" == changed:* ]]; then
    echo ""
    echo "Validating YAML syntax..."
    if ! validate_yaml "$LITELLM_CONFIG"; then
      echo "❌ Config changes invalid — aborting restart"
      rm -f "$sync_response" "$reconcile_response"
      return 1
    fi
    echo "✓ YAML valid"
    echo ""
    echo "Config updated — restarting LiteLLM..."
    docker compose -f "$SCRIPT_DIR/docker-compose.yml" restart litellm
    echo "Done. New model list:"
    sleep 12
    cmd_models
  else
    echo ""
    echo "No config changes needed."
  fi
  rm -f "$sync_response" "$reconcile_response"
}

cmd_sync_models_legacy() {
  local api_key
  api_key=$(get_api_key)
  local AUDIT_LOG="$SCRIPT_DIR/sync-models.log"

  echo "Fetching model list from CLIProxyAPI..."
  local raw_models
  raw_models=$(curl -sf -H "Authorization: Bearer $api_key" \
    "http://localhost:$CLIPROXY_PORT/v1/models" \
    | python3 -c "import sys,json; [print(m['id']) for m in json.load(sys.stdin).get('data',[])]" \
    2>/dev/null) || { echo "CLIProxyAPI not reachable on port $CLIPROXY_PORT"; exit 1; }

  local changed=false

  # --- Check existing config entries for dead models ---
  echo ""
  echo "Checking existing models for availability..."
  while IFS= read -r alias; do
    # Extract upstream model name for this alias
    local upstream
    upstream=$(python3 -c "
import sys, re
with open('$LITELLM_CONFIG') as f: txt = f.read()
m = re.search(r'model_name: ${alias}\n\s+litellm_params:\n\s+model: openai/(\S+)', txt)
print(m.group(1) if m else '')
" 2>/dev/null)
    [ -z "$upstream" ] && continue

    local status=0
    probe_model "$upstream" || status=$?

    if [ "$status" = "0" ]; then
      echo "  OK   $alias"
    elif [ "$status" = "42" ] || [ "$status" = "53" ]; then
      # Transient error (rate limit or unavailable) — don't remove, just warn
      echo "  WARN $alias — rate limited / temporarily unavailable (HTTP $PROBE_HTTP_CODE) — skipping removal"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) SKIPPED $alias (probe $PROBE_HTTP_CODE - transient, will retry next sync)" >> "$AUDIT_LOG"
    else
      # 404 or other error — model likely doesn't exist, mark for removal
      echo "  DEAD $alias (HTTP $PROBE_HTTP_CODE) — removing"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) REMOVED $alias (probe $PROBE_HTTP_CODE - model not found)" >> "$AUDIT_LOG"
      # Use Python to safely remove the model block from YAML
      python3 - "$LITELLM_CONFIG" "$alias" <<'PYEOF'
import sys, re
path, alias = sys.argv[1], sys.argv[2]
with open(path) as f: txt = f.read()
# Safer pattern: match model_name block up to next model or settings
pattern = rf'\n  - model_name: {re.escape(alias)}\n    litellm_params:.*?(?=\n  - model_name:|\ngeneral_settings:)'
txt = re.sub(pattern, '', txt, flags=re.DOTALL)
with open(path, 'w') as f: f.write(txt)
PYEOF
      gemini_map_remove "$alias"
      changed=true
    fi
  done < <(grep 'model_name:' "$LITELLM_CONFIG" | awk '{print $3}')

  # --- Check for new models not yet in config ---
  echo ""
  echo "Checking for new models from CLIProxyAPI..."
  while IFS= read -r model_id; do
    local alias
    alias=$(model_to_alias "$model_id")
    if alias_in_config "$alias"; then
      continue
    fi
    echo -n "  NEW  $model_id → testing... "
    local status=0
    probe_model "$model_id" || status=$?

    if [ "$status" = "0" ]; then
      echo "OK — adding as $alias"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ADDED $alias (upstream: $model_id)" >> "$AUDIT_LOG"
      # Append new entry before the general_settings block
      # Use os.environ/CLIPROXY_API_KEY reference, not literal key value
      python3 - "$LITELLM_CONFIG" "$alias" "$model_id" "$CLIPROXY_PORT" <<'PYEOF'
import sys
path, alias, model_id, port = sys.argv[1:]
entry = f"""
  - model_name: {alias}
    litellm_params:
      model: openai/{model_id}
      api_base: http://cliproxy:{port}/v1
      api_key: os.environ/CLIPROXY_API_KEY
"""
with open(path) as f: txt = f.read()
txt = txt.replace('\ngeneral_settings:', entry + '\ngeneral_settings:', 1)
with open(path, 'w') as f: f.write(txt)
PYEOF
      gemini_map_add "$model_id" "$alias"
      changed=true
    elif [ "$status" = "42" ] || [ "$status" = "53" ]; then
      # Transient error — skip this run, will retry on next sync
      echo "rate limited / unavailable (HTTP $PROBE_HTTP_CODE) — skipping"
    else
      # 404 or other error — model not available
      echo "not available (HTTP $PROBE_HTTP_CODE) — skipping"
    fi
  done <<< "$raw_models"

  # Ensure every model entry has model_info with base_model + cost/feature data
  echo ""
  echo "Syncing cost metadata from LiteLLM registry..."
  local costs_file mi_result
  costs_file=$(fetch_config_model_costs)
  mi_result=$(apply_model_info "$costs_file")
  rm -f "$costs_file"
  if [ "$mi_result" = "changed" ]; then
    echo "  Cost/feature metadata written."
    changed=true
  else
    echo "  Cost/feature metadata already current."
  fi

  # Dynamic Fallbacks generation & synchronization
  echo ""
  echo "Syncing LiteLLM fallbacks..."
  local fb_result
  fb_result=$(apply_fallbacks)
  if [ "$fb_result" = "fallbacks_updated" ]; then
    echo "  Fallback rules successfully updated."
    changed=true
  elif [ "$fb_result" = "no_change" ]; then
    echo "  Fallback rules already current."
  else
    echo "  Warning: could not apply fallbacks ($fb_result)."
  fi

  if [ "$changed" = true ]; then
    echo ""
    echo "Validating YAML syntax..."
    if ! validate_yaml "$LITELLM_CONFIG"; then
      echo "❌ Config changes invalid — aborting restart"
      return 1
    fi
    echo "✓ YAML valid"
    echo ""
    echo "Config updated — restarting LiteLLM..."
    docker compose -f "$SCRIPT_DIR/docker-compose.yml" restart litellm
    echo "Done. New model list:"
    sleep 12
    cmd_models
  else
    echo ""
    echo "No changes needed."
  fi
}

cmd_sync_models() {
  case "${1:-}" in
    --legacy|legacy)
      echo "Using legacy direct sync-models path by explicit request."
      cmd_sync_models_legacy
      ;;
    "")
      if [ "${CLIPROXY_SYNC_MODE:-registry}" = "legacy" ]; then
        echo "Using legacy direct sync-models path because CLIPROXY_SYNC_MODE=legacy."
        cmd_sync_models_legacy
      else
        cmd_sync_models_registry
      fi
      ;;
    *)
      echo "Usage: $0 sync-models [--legacy]"
      return 2
      ;;
  esac
}

cmd_health() {
  local api_key
  api_key=$(get_api_key)

  echo "=== CLIProxyAPI health ==="
  local model_count
  if model_count=$(curl -sf -H "Authorization: Bearer $api_key" \
    "http://localhost:$CLIPROXY_PORT/v1/models" \
    | python3 -c "import sys,json; d=json.load(sys.stdin).get('data',[]); print(len(d))" 2>/dev/null); then
    echo "  Status : UP"
    echo "  Models : $model_count available"
  else
    echo "  Status : DOWN (not reachable on port $CLIPROXY_PORT)"
  fi

  echo ""
  echo "=== Auth tokens ==="
  local auth_dir="$HOME/.cli-proxy-api"
  if [ -d "$auth_dir" ]; then
    local found=false
    for f in "$auth_dir"/*.json; do
      [ -f "$f" ] || continue
      found=true
      python3 - "$f" <<'PYEOF'
import sys, json, datetime
path = sys.argv[1]
with open(path) as f:
    d = json.load(f)
ptype  = d.get('type', '?')
email  = d.get('email', '?')
disabled = d.get('disabled', False)
last_ref = d.get('last_refresh', '')
expired  = d.get('expired', '')

status = 'DISABLED' if disabled else 'active'
if expired:
    try:
        exp_dt = datetime.datetime.fromisoformat(expired.replace('Z','+00:00'))
        now = datetime.datetime.now(datetime.timezone.utc)
        diff = exp_dt - now
        age = f"(access token expires in {int(diff.total_seconds()//60)}m)"
        if diff.total_seconds() < 0:
            age = "(access token EXPIRED — CLIProxyAPI should auto-refresh)"
    except:
        age = ''
else:
    age = ''

login_cmd = {'claude': 'login-claude', 'codex': 'login-codex', 'gemini': 'login-gemini'}.get(ptype, 'login-all')
print(f"  [{ptype:6}] {email}  {status}  last_refresh={last_ref[:19]}  {age}")
print(f"           If seeing 401 errors → ./cliproxy-setup.sh {login_cmd}")
PYEOF
    done
    if [ "$found" = false ]; then
      echo "  No auth files found in $auth_dir"
      echo "  Run: $0 login-all"
    fi
  else
    echo "  Auth directory not found: $auth_dir"
  fi
  echo ""
  echo "  Note: 401 errors in LiteLLM logs mean a provider token needs refresh."
  echo "  OAuth tokens auto-refresh every ~15min while the container is running."
  echo "  Force re-auth with: ./cliproxy-setup.sh login-claude | login-codex | login-gemini"
  echo ""
  echo "  For re-auth on a remote server, open SSH port forwards first (local terminal):"
  echo "    ssh -L 54545:127.0.0.1:54545 -L 1455:127.0.0.1:1455 -L 8085:127.0.0.1:8085 user@gateway-host.example -p 22"

  echo ""
  echo "=== Docker container ==="
  docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps cliproxy 2>/dev/null \
    | grep -v '^NAME' | awk '{printf "  %-20s %s\n", $1, $4}' \
    || echo "  (docker compose not available)"
}

cmd_models() {
  local api_key
  api_key=$(get_api_key)
  echo "Models from CLIProxyAPI:"
  curl -sf -H "Authorization: Bearer $api_key" "http://localhost:$CLIPROXY_PORT/v1/models" \
    | python3 -c "
import sys, json
data = json.load(sys.stdin).get('data', [])
by_type = {}
for m in data:
    name = m['id']
    t = 'claude' if 'claude' in name else 'gemini' if 'gemini' in name else 'gpt/codex'
    by_type.setdefault(t, []).append(name)
for t, names in sorted(by_type.items()):
    print(f'  [{t}]')
    for n in sorted(names): print(f'    {n}')
" 2>/dev/null || echo "  CLIProxyAPI not reachable on port $CLIPROXY_PORT"
}

cmd_apply() {
  echo "=== Applying updates ==="
  echo ""
  echo "Step 1: Check for CLIProxyAPI upgrade"
  cmd_upgrade
  echo ""
  echo "Step 2: Sync model registry and reconcile LiteLLM config"
  cmd_sync_models
  echo ""
  echo "Step 3: Health check"
  cmd_health
}

# ──────────────────────────────────────────────
# Main dispatch
# ──────────────────────────────────────────────

cmd="${1:-help}"

case "$cmd" in
  install)         cmd_install ;;
  upgrade)         cmd_upgrade ;;
  sync-models)     cmd_sync_models "${@:2}" ;;
  health)          cmd_health ;;
  models)          cmd_models ;;
  quota-summary)   cmd_quota_summary ;;
  apply)           cmd_apply ;;

  login-claude)
    require_bin
    echo "Opening browser for Claude Pro/Max OAuth..."
    echo "(Callback on port 54545 — keep this terminal open)"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --claude-login
    ;;

  login-codex)
    require_bin
    echo "Opening browser for ChatGPT Plus/Pro OAuth..."
    echo "(Callback on port 1455 — requires ChatGPT Plus or Pro)"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --codex-login
    ;;

  login-gemini)
    require_bin
    echo "Opening browser for Gemini / Google account OAuth..."
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --login
    ;;

  login-antigravity)
    require_bin
    echo "Opening browser for Antigravity / Google account OAuth..."
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --antigravity-login
    ;;

  login-grok)
    require_bin
    echo "Opening browser for Grok / X Premium OAuth..."
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --grok-login
    ;;

  login-kimi)
    require_bin
    echo "Opening browser for Kimi OAuth..."
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --kimi-login
    ;;

  login-all)
    require_bin
    echo "=== Login to all providers ==="
    echo "Step 1/5: Claude Pro/Max"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --claude-login
    echo "Step 2/5: ChatGPT Plus/Pro (Codex)"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --codex-login
    echo "Step 3/5: Antigravity / Google account"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --antigravity-login
    echo "Step 4/5: Grok / X Premium"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --grok-login
    echo "Step 5/5: Kimi"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --kimi-login
    ;;

  login-headless)
    require_bin
    PROVIDER="${2:-claude}"
    case "$PROVIDER" in
      claude)       "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --no-browser --claude-login ;;
      codex)        "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --no-browser --codex-login ;;
      gemini)       "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --no-browser --login ;;
      antigravity)  "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --no-browser --antigravity-login ;;
      grok)         "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --no-browser --grok-login ;;
      kimi)         "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --no-browser --kimi-login ;;
      *) echo "Unknown provider: $PROVIDER (use: claude, codex, gemini, antigravity, grok, kimi)"; exit 1 ;;
    esac
    ;;

  start)
    # For direct host testing; prefer Docker: docker compose up -d cliproxy
    require_bin
    echo "Starting CLIProxyAPI on port $CLIPROXY_PORT (host mode)..."
    echo "NOTE: For production use 'docker compose up -d cliproxy' instead."
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG"
    ;;

  test)
    MODEL="${2:-claude-sonnet-4-6}"
    echo "Testing LiteLLM → CLIProxyAPI with model: $MODEL"
    curl -s -X POST http://localhost:4000/v1/chat/completions \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $LITELLM_KEY" \
      -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello in one sentence.\"}],\"max_tokens\":30}" \
      | python3 -m json.tool
    ;;

  test-direct)
    MODEL="${2:-claude-sonnet-4-6}"
    API_KEY=$(get_api_key)
    echo "Testing CLIProxyAPI directly with model: $MODEL"
    curl -s -X POST "http://localhost:$CLIPROXY_PORT/v1/chat/completions" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $API_KEY" \
      -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello in one sentence.\"}],\"max_tokens\":30}" \
      | python3 -m json.tool
    ;;

  test-all)
    # One representative model per provider; tests the full translator→litellm→cliproxy path
    declare -A PROVIDER_MODELS=(
      [claude]="claude-sonnet-4-6"
      [gemini]="gemini-3-flash"
      [openai]="gpt-5-4"
      [xai]="grok-4"
      [kimi]="kimi-k2"
    )
    PASS=0; FAIL=0; SKIP=0
    echo "=== Provider flow test (translator → LiteLLM → CLIProxy) ==="
    for provider in claude gemini openai xai kimi; do
      model="${PROVIDER_MODELS[$provider]}"
      # skip if model not in litellm config
      if ! grep -q "model_name: ${model}$" "$LITELLM_CONFIG" 2>/dev/null; then
        printf "  %-10s %-28s SKIP (not in config)\n" "$provider" "$model"
        (( SKIP++ )) || true
        continue
      fi
      response=$(curl -s --max-time 30 -X POST http://localhost:4000/v1/chat/completions \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $LITELLM_KEY" \
        -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly one word: OK\"}],\"max_tokens\":10}")
      content=$(echo "$response" | python3 -c \
        "import sys,json; r=json.load(sys.stdin); print(r['choices'][0]['message']['content'].strip())" 2>/dev/null)
      if [ -n "$content" ]; then
        printf "  %-10s %-28s PASS  (%s)\n" "$provider" "$model" "$content"
        (( PASS++ )) || true
      else
        err=$(echo "$response" | python3 -c \
          "import sys,json; r=json.load(sys.stdin); print(r.get('error',{}).get('message','no response')[:60])" 2>/dev/null \
          || echo "empty response")
        printf "  %-10s %-28s FAIL  (%s)\n" "$provider" "$model" "$err"
        (( FAIL++ )) || true
      fi
    done
    echo ""
    echo "Results: ${PASS} passed, ${FAIL} failed, ${SKIP} skipped"
    [ "$FAIL" -eq 0 ]
    ;;

  *)
    cat <<EOF
Usage: $0 <command> [args]

Setup:
  install              Download CLIProxyAPI binary to ~/.cliproxy/
  login-claude         Authenticate Claude Pro/Max (browser OAuth, port 54545)
  login-codex          Authenticate ChatGPT Plus/Pro (browser OAuth, port 1455)
  login-gemini         Authenticate Gemini / Google account (browser OAuth)
  login-antigravity    Authenticate Antigravity / Google account (browser OAuth)
  login-grok           Authenticate Grok / X Premium (browser OAuth)
  login-kimi           Authenticate Kimi (browser OAuth)
  login-all            Authenticate all providers sequentially
  login-headless <p>   Headless OAuth for SSH servers (p: claude|codex|gemini|antigravity|grok|kimi)

Operations:
  apply                Full update workflow: upgrade → sync-models → health
  sync-models          Sync via translator registry APIs; writes reconciled config
  sync-models --legacy Emergency direct mutation path for one-release rollback
  upgrade              Download newer binary + rebuild Docker image if available
  health               Show per-provider auth status and container state
  models               List models grouped by provider from CLIProxyAPI
  quota-summary        Per-credential request counts and last-refresh timestamps
  test [model]         Test model end-to-end through LiteLLM
  test-direct [model]  Test model directly against CLIProxyAPI
  test-all             Test one model per provider; reports pass/fail/skip

Legacy (prefer Docker):
  start                Run CLIProxyAPI directly on host (for debugging)

First-time setup:
  $0 install
  $0 login-all
  docker compose build cliproxy
  docker compose up -d
  sleep 15 && $0 sync-models

Update workflow (run periodically):
  $0 apply
EOF
    ;;
esac
