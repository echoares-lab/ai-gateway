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
LITELLM_KEY="${LITELLM_MASTER_KEY:-$(grep '^LITELLM_MASTER_KEY=' "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2)}"

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
EOF
  echo "Config written to $CLIPROXY_CONFIG"
  echo "CLIProxyAPI API key: $apikey"
}

get_api_key() {
  grep -A2 'api-keys:' "$CLIPROXY_CONFIG" 2>/dev/null | grep '^\s*-' | sed 's/.*"\(.*\)".*/\1/' | head -1
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
import os, json

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

# Probe a model via CLIProxyAPI directly; return 0 if it responds with a choice
probe_model() {
  local model="$1"
  local api_key
  api_key=$(get_api_key)
  local result
  result=$(curl -s --max-time 20 -X POST "http://localhost:$CLIPROXY_PORT/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $api_key" \
    -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":3}" 2>/dev/null)
  echo "$result" | python3 -c "import sys,json; r=json.load(sys.stdin); exit(0 if r.get('choices') else 1)" 2>/dev/null
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

cmd_sync_models() {
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

    if probe_model "$upstream"; then
      echo "  OK   $alias"
    else
      echo "  DEAD $alias — removing"
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) REMOVED $alias (probe 503)" >> "$AUDIT_LOG"
      python3 - "$LITELLM_CONFIG" "$alias" <<'PYEOF'
import sys, re
path, alias = sys.argv[1], sys.argv[2]
with open(path) as f: txt = f.read()
pattern = rf'\n  - model_name: {re.escape(alias)}\n    litellm_params:.*?api_key: [^\n]+\n'
txt = re.sub(pattern, '\n', txt, flags=re.DOTALL)
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
    if probe_model "$model_id"; then
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
    else
      echo "503 — skipping"
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
  echo "    ssh -L 54545:127.0.0.1:54545 -L 1455:127.0.0.1:1455 -L 8085:127.0.0.1:8085 dev@10.10.10.52 -p 22"

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
  echo "Step 2: Sync model list with LiteLLM config"
  cmd_sync_models
  echo ""
  echo "Step 3: Health check"
  cmd_health
}

cmd_quota_summary() {
  local api_key
  api_key=$(get_api_key)
  echo "Quota / usage summary from CLIProxyAPI:"
  curl -sf -H "Authorization: Bearer $api_key" "http://localhost:$CLIPROXY_PORT/v1/models" \
    | python3 -c "
import sys, json, collections
data = json.load(sys.stdin).get('data', [])
by_provider = collections.Counter(m.get('owned_by', 'unknown') for m in data)
print()
print('  Provider           Models')
print('  ──────────────────────────────')
for provider, count in sorted(by_provider.items()):
    print(f'  {provider:<20} {count}')
print()
print(f'  Total: {sum(by_provider.values())} models across {len(by_provider)} providers')
" 2>/dev/null || echo "  CLIProxyAPI not reachable on port $CLIPROXY_PORT"
}

# ──────────────────────────────────────────────
# Main dispatch
# ──────────────────────────────────────────────

cmd="${1:-help}"

case "$cmd" in
  install)         cmd_install ;;
  upgrade)         cmd_upgrade ;;
  sync-models)     cmd_sync_models ;;
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
  sync-models          Probe all models; add new working ones, remove dead ones
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
