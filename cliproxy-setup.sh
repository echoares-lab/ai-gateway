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
# every openai/ model currently in LITELLM_CONFIG. Returns a JSON map:
#   {"model-id": {"input_cost_per_token": N, ...}, ...}
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
  # Stdout is captured to a file because litellm prints ANSI startup messages to
  # stdout at the fd level, which sys.stdout redirection cannot suppress.
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
  # litellm contaminates stdout with startup messages including JSON-like lines.
  # A unique sentinel prefix guarantees we extract only our output line.
  # Write directly to costs_file to avoid bash variable corruption of large JSON.
  if grep -q '^__COSTS__:' "$tmp_out" 2>/dev/null; then
    grep '^__COSTS__:' "$tmp_out" | tail -1 | sed 's/^__COSTS__://' > "$costs_file"
  else
    echo '{}' > "$costs_file"
  fi
  rm -f "$tmp_out"
  echo "$costs_file"
}

# Add or merge model_info blocks into LITELLM_CONFIG for all openai/ entries that
# lack a base_model field. Preserves existing model_info fields such as
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
        # Collect the full entry: all 4-space-indented lines plus any blank lines
        entry = [line]
        i += 1
        while i < len(lines) and (lines[i].startswith('    ') or lines[i].strip() == ''):
            entry.append(lines[i])
            i += 1

        entry_text = ''.join(entry)
        m = re.search(r'model: openai/(\S+)', entry_text)

        # Skip entries without an openai/ model, or already having base_model
        if not m or 'base_model:' in entry_text:
            out.extend(entry)
            continue

        model_id = m.group(1)
        new_lines = build_info_lines(model_id, costs.get(model_id, {}))

        if any(l.rstrip() == '    model_info:' for l in entry):
            # Merge into existing model_info block (preserves other fields)
            merged = []
            for el in entry:
                merged.append(el)
                if el.rstrip() == '    model_info:':
                    merged.extend(new_lines)
            out.extend(merged)
        else:
            # Insert new model_info block after the last litellm_params line
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
      python3 - "$LITELLM_CONFIG" "$alias" <<'PYEOF'
import sys, re
path, alias = sys.argv[1], sys.argv[2]
with open(path) as f: txt = f.read()
# Match the entry header plus all 4-space-indented content (litellm_params,
# model_info, comments) so the full block is removed, not just litellm_params.
pattern = rf'\n  - model_name: {re.escape(alias)}\n(?:    [^\n]*\n)*'
txt = re.sub(pattern, '\n', txt)
with open(path, 'w') as f: f.write(txt)
PYEOF
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
      local api_key_val
      api_key_val=$(get_api_key)
      # Append new entry before the general_settings block
      python3 - "$LITELLM_CONFIG" "$alias" "$model_id" "$api_key_val" "$CLIPROXY_PORT" <<'PYEOF'
import sys
path, alias, model_id, api_key, port = sys.argv[1:]
entry = f"""
  - model_name: {alias}
    litellm_params:
      model: openai/{model_id}
      api_base: http://cliproxy:{port}/v1
      api_key: {api_key}
"""
with open(path) as f: txt = f.read()
txt = txt.replace('\ngeneral_settings:', entry + '\ngeneral_settings:', 1)
with open(path, 'w') as f: f.write(txt)
PYEOF
      changed=true
    else
      echo "503 — skipping"
    fi
  done <<< "$raw_models"

  # Ensure every model entry has model_info with base_model + cost data
  echo ""
  echo "Syncing cost metadata from LiteLLM registry..."
  local costs_file mi_result
  costs_file=$(fetch_config_model_costs)
  mi_result=$(apply_model_info "$costs_file")
  rm -f "$costs_file"
  if [ "$mi_result" = "changed" ]; then
    echo "  Cost metadata written."
    changed=true
  else
    echo "  Cost metadata already current."
  fi

  if [ "$changed" = true ]; then
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

  login-all)
    require_bin
    echo "=== Login to all three providers ==="
    echo "Step 1/3: Claude Pro/Max"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --claude-login
    echo "Step 2/3: ChatGPT Plus/Pro (Codex)"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --codex-login
    echo "Step 3/3: Gemini / Google account"
    "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --login
    ;;

  login-headless)
    require_bin
    PROVIDER="${2:-claude}"
    case "$PROVIDER" in
      claude)  "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --no-browser --claude-login ;;
      codex)   "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --no-browser --codex-login ;;
      gemini)  "$CLIPROXY_BIN" -config "$CLIPROXY_CONFIG" --no-browser --login ;;
      *) echo "Unknown provider: $PROVIDER (use: claude, codex, gemini)"; exit 1 ;;
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

  *)
    cat <<EOF
Usage: $0 <command> [args]

Setup:
  install              Download CLIProxyAPI binary to ~/.cliproxy/
  login-claude         Authenticate Claude Pro/Max (browser OAuth, port 54545)
  login-codex          Authenticate ChatGPT Plus/Pro (browser OAuth, port 1455)
  login-gemini         Authenticate Gemini / Google account (browser OAuth)
  login-all            Authenticate all three providers sequentially
  login-headless <p>   Headless OAuth for SSH servers (p: claude|codex|gemini)

Operations:
  apply                Full update workflow: upgrade → sync-models → health
  sync-models          Probe all models; add new working ones, remove dead ones
  upgrade              Download newer binary + rebuild Docker image if available
  health               Show per-provider auth status and container state
  models               List models grouped by provider from CLIProxyAPI
  test [model]         Test model end-to-end through LiteLLM
  test-direct [model]  Test model directly against CLIProxyAPI

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
