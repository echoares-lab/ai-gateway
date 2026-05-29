#!/usr/bin/env python3

"""
Automates setup of LiteLLM teams and API keys for each repository in a
GitHub organization. Creates one team per repo and one key per client,
then writes the correct env vars into each repo's .env file.

Requirements:
  - requests (`pip install requests`)
  - gh CLI (https://cli.github.com/) — logged in with repo read access
"""

import json
import os
import re
import subprocess
import sys

try:
    import requests
except ImportError:
    sys.exit("[!] Missing 'requests'. Run: pip install requests")

# --- Configuration ---

ORG = "echoares-lab"

# Public-facing gateway endpoint (what clients connect to).
GATEWAY_API_URL = "http://localhost:4000"

# LiteLLM admin API — port 4001 maps to the LiteLLM container.
LITELLM_ADMIN_URL = "http://localhost:4001"

# Read master key from env or .env file; fall back to default only as last resort.
def _load_master_key():
    if os.environ.get("LITELLM_MASTER_KEY"):
        return os.environ["LITELLM_MASTER_KEY"]
    env_file = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            if line.startswith("LITELLM_MASTER_KEY="):
                return line.split("=", 1)[1].strip()
    return "sk-1234"

LITELLM_MASTER_KEY = _load_master_key()

CLIENTS = ["codex", "gemini", "claude", "cursor", "antigravity"]

# Codex CLI (Rust binary) ignores OPENAI_BASE_URL.  It reads OPENAI_API_KEY
# from the environment, but only routes via HTTP Responses API when it has no
# stored ChatGPT tokens.  We isolate it with a dedicated CODEX_HOME so the
# gateway config never collides with the user's personal ChatGPT OAuth session.
CODEX_GATEWAY_HOME = os.path.expanduser("~/.codex-gateway")

# Maps each client to the env vars its CLI actually reads.
CLIENT_CONFIG = {
    "claude": {
        "base_var": "ANTHROPIC_BASE_URL",    # Claude CLI: ANTHROPIC_BASE_URL
        "key_var":  "ANTHROPIC_API_KEY",
        "base_path": "",                      # Claude CLI appends /v1/messages itself
    },
    "codex": {
        # CODEX_HOME isolates the gateway config from the user's default ~/.codex.
        # OPENAI_API_KEY triggers HTTP Responses API mode (no ChatGPT tokens stored
        # in CODEX_HOME, so Codex falls back to API key auth).
        "base_var":   "CODEX_HOME",
        "base_value": CODEX_GATEWAY_HOME,     # static path, not a URL
        "key_var":    "OPENAI_API_KEY",
        "base_path":  "/v1",                  # used for openai_base_url in config.toml
    },
    "gemini": {
        "base_var": "GOOGLE_GEMINI_BASE_URL", # Gemini CLI reads GOOGLE_GEMINI_BASE_URL
        "key_var":  "GEMINI_API_KEY",
        "base_path": "",                      # Gemini CLI adds /v1beta/models/... itself
    },
    "cursor": {
        "base_var": "CURSOR_API_BASE",
        "key_var":  "CURSOR_API_KEY",
        "base_path": "/v1",
    },
    "antigravity": {
        "base_var": "ANTIGRAVITY_API_BASE",
        "key_var":  "ANTIGRAVITY_API_KEY",
        "base_path": "/v1",
    },
}

# --- Helpers ---

def log(msg):
    print(f"[*] {msg}")

def warn(msg):
    print(f"[!] {msg}", file=sys.stderr)

def run_command(command):
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        warn(f"Command failed: {command}\n{e.stderr}")
        return None

def safe_update_env(env_path, variables, remove_vars=()):
    """Replace named vars in env_path (or create it) with new values.
    vars in remove_vars are stripped without replacement (stale key cleanup)."""
    lines = open(env_path).readlines() if os.path.exists(env_path) else []
    var_names = {var for var, _ in variables} | set(remove_vars)
    kept = [l for l in lines if l.split("=", 1)[0].strip() not in var_names]
    kept += [f"{var}={value}\n" for var, value in variables]
    with open(env_path, "w") as f:
        f.writelines(kept)

def _read_env_var(env_path, var_name):
    """Read a single var value from an env file, or None if not found."""
    if not os.path.exists(env_path):
        return None
    for line in open(env_path):
        line = line.strip()
        if line.startswith(f"{var_name}="):
            return line.split("=", 1)[1]
    return None

def ensure_gitignore(repo_dir):
    path = os.path.join(repo_dir, ".gitignore")
    if not os.path.exists(path):
        open(path, "w").write(".env\n")
        log("Created .gitignore with .env entry.")
    else:
        content = open(path).read()
        if ".env" not in content:
            open(path, "a").write("\n.env\n")
            log("Added .env to existing .gitignore.")

# --- Codex gateway setup ---

def _read_codex_toml(config_path):
    """Parse codex config.toml into (global_kvs dict, project_trust dict)."""
    global_kvs, project_trust, current_project = {}, {}, None
    if not os.path.exists(config_path):
        return global_kvs, project_trust
    for line in open(config_path):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r'\[projects\."(.+?)"\]', stripped)
        if m:
            current_project = m.group(1)
            continue
        if stripped.startswith("["):
            current_project = None
            continue
        if "=" in stripped:
            k, _, v = stripped.partition("=")
            k, v = k.strip(), v.strip().strip('"')
            if current_project is not None:
                if k == "trust_level":
                    project_trust[current_project] = v
            else:
                global_kvs[k] = v
    return global_kvs, project_trust

def _write_codex_toml(config_path, global_kvs, project_trust):
    """Write codex config.toml from (global_kvs, project_trust) dicts."""
    lines = [f'{k} = "{v}"\n' for k, v in global_kvs.items()]
    for path, level in sorted(project_trust.items()):
        lines += [f'\n[projects."{path}"]\n', f'trust_level = "{level}"\n']
    with open(config_path, "w") as f:
        f.writelines(lines)

def _setup_codex_gateway_home(repo_dir: str):
    """
    Create/update ~/.codex-gateway/config.toml with:
      - openai_base_url pointing at our gateway
      - approval_policy = "never"  (yolo / full-auto mode)
      - [projects."<repo_dir>"] trust_level = "trusted"  (per-repo trust)

    No auth.json is written — the absence of stored ChatGPT tokens causes
    Codex to fall back to OPENAI_API_KEY env-var API-key mode.
    User's default ~/.codex (ChatGPT OAuth) is untouched.
    """
    os.makedirs(CODEX_GATEWAY_HOME, exist_ok=True)
    config_path = os.path.join(CODEX_GATEWAY_HOME, "config.toml")

    global_kvs, project_trust = _read_codex_toml(config_path)
    global_kvs["openai_base_url"] = f"{GATEWAY_API_URL}/v1"
    global_kvs["approval_policy"] = "never"
    project_trust[repo_dir] = "trusted"

    _write_codex_toml(config_path, global_kvs, project_trust)
    log(f"  codex: updated {config_path} (approval_policy=never, trusted {repo_dir})")

# --- Gemini trust setup ---

def _setup_gemini_trust(repo_dir: str):
    """Add repo_dir to ~/.gemini/trustedFolders.json (TRUST_FOLDER level)."""
    trusted_path = os.path.expanduser("~/.gemini/trustedFolders.json")
    trusted = {}
    if os.path.exists(trusted_path):
        try:
            trusted = json.loads(open(trusted_path).read())
        except Exception:
            pass
    trusted[repo_dir] = "TRUST_FOLDER"
    with open(trusted_path, "w") as f:
        json.dump(trusted, f, indent=2)
        f.write("\n")
    log(f"  gemini: trusted {repo_dir} in {trusted_path}")

# --- ~/.bashrc gateway wrappers ---

_BASHRC_SENTINEL_START = "# >>> ai-gateway wrappers start <<<"
_BASHRC_SENTINEL_END   = "# >>> ai-gateway wrappers end <<<"
_BASHRC_WRAPPER = """\
# >>> ai-gateway wrappers start <<<
# Managed by setup_litellm_teams.py — do not edit manually.

# Codex: per-repo key from .env, CODEX_HOME → gateway config, yolo mode
export CODEX_HOME=~/.codex-gateway
codex() {
    local key dir="$PWD"
    while [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/.env" ]]; then
            key=$(grep '^OPENAI_API_KEY=' "$dir/.env" | cut -d= -f2 | head -1)
            [[ -n "$key" ]] && break
        fi
        dir=$(dirname "$dir")
    done
    [[ -z "$key" ]] && echo "[codex-gateway] no OPENAI_API_KEY in .env above $PWD" >&2
    CODEX_HOME=~/.codex-gateway OPENAI_API_KEY="$key" command codex -c "api_key=\\"$key\\"" "$@"
}

# Claude: per-repo key from .env, routes via gateway, yolo mode
claude() {
    local key dir="$PWD"
    while [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/.env" ]]; then
            key=$(grep '^ANTHROPIC_API_KEY=' "$dir/.env" | cut -d= -f2 | head -1)
            [[ -n "$key" ]] && break
        fi
        dir=$(dirname "$dir")
    done
    [[ -z "$key" ]] && echo "[claude-gateway] no ANTHROPIC_API_KEY in .env above $PWD" >&2
    ANTHROPIC_BASE_URL="http://localhost:4000" ANTHROPIC_API_KEY="$key" command claude --dangerously-skip-permissions "$@"
}

# Gemini: per-repo key from .env, routes via gateway, yolo mode
gemini() {
    local key dir="$PWD"
    while [[ "$dir" != "/" ]]; do
        if [[ -f "$dir/.env" ]]; then
            key=$(grep '^GEMINI_API_KEY=' "$dir/.env" | cut -d= -f2 | head -1)
            [[ -n "$key" ]] && break
        fi
        dir=$(dirname "$dir")
    done
    [[ -z "$key" ]] && echo "[gemini-gateway] no GEMINI_API_KEY in .env above $PWD" >&2
    GOOGLE_GEMINI_BASE_URL="http://localhost:4000" GEMINI_API_KEY="$key" command gemini --yolo "$@"
}
# >>> ai-gateway wrappers end <<<
"""

def _ensure_bashrc_wrapper():
    """Write (or replace) the gateway wrapper block in ~/.bashrc."""
    bashrc = os.path.expanduser("~/.bashrc")
    content = open(bashrc).read() if os.path.exists(bashrc) else ""

    # Handle old single-sentinel block name as well as new name.
    old_start = "# >>> codex-gateway wrapper start <<<"
    old_end   = "# >>> codex-gateway wrapper end <<<"
    for s, e in [(old_start, old_end), (_BASHRC_SENTINEL_START, _BASHRC_SENTINEL_END)]:
        si, ei = content.find(s), content.find(e)
        if si != -1 and ei != -1:
            content = content[:si] + content[ei + len(e):]
            break

    content = content.rstrip("\n") + "\n\n" + _BASHRC_WRAPPER
    with open(bashrc, "w") as f:
        f.write(content)
    log("  bashrc: updated gateway wrappers (source ~/.bashrc to activate)")


# --- Main ---

def main():
    headers = {
        "Authorization": f"Bearer {LITELLM_MASTER_KEY}",
        "Content-Type": "application/json",
    }

    log(f"Using LiteLLM at {LITELLM_ADMIN_URL}")
    log(f"Fetching repos from {ORG}...")

    repo_names_str = run_command(f"gh repo list {ORG} --json name -q '.[].name'")
    if not repo_names_str:
        sys.exit(f"[!] No repositories found for {ORG}.")

    repos = repo_names_str.splitlines()
    log(f"Found {len(repos)} repos: {', '.join(repos)}")

    # Fetch existing teams once up front to avoid duplicates on re-runs.
    try:
        resp = requests.get(f"{LITELLM_ADMIN_URL}/team/list", headers=headers, timeout=10)
        resp.raise_for_status()
        existing = resp.json() if isinstance(resp.json(), list) else resp.json().get("teams", [])
        existing_teams = {t["team_alias"]: t["team_id"] for t in existing if t.get("team_alias")}
        log(f"Existing teams: {', '.join(existing_teams) or '(none)'}")
    except requests.RequestException as e:
        warn(f"Could not fetch existing teams: {e}. Will attempt to create all.")
        existing_teams = {}

    for repo in repos:
        repo_dir = os.path.join(os.path.expanduser("~"), "repos", repo)
        if not os.path.isdir(repo_dir):
            log(f"  {repo}: no local clone at {repo_dir}, skipping.")
            continue

        log(f"\n--- {repo} ---")

        # Reuse existing team or create a new one — never create duplicates.
        if repo in existing_teams:
            team_id = existing_teams[repo]
            log(f"  Team already exists: {team_id}")
        else:
            try:
                resp = requests.post(
                    f"{LITELLM_ADMIN_URL}/team/new",
                    headers=headers,
                    json={"team_alias": repo},
                    timeout=10,
                )
                resp.raise_for_status()
                team_id = resp.json().get("team_id")
                existing_teams[repo] = team_id
                log(f"  Created team: {team_id}")
            except requests.RequestException as e:
                warn(f"  Failed to create team for {repo}: {e}")
                continue

        env_vars = []
        stale_vars = []
        env_path = os.path.join(repo_dir, ".env")

        for client in CLIENTS:
            alias = f"{repo}-{client}"
            cfg = CLIENT_CONFIG[client]
            try:
                resp = requests.post(
                    f"{LITELLM_ADMIN_URL}/key/generate",
                    headers=headers,
                    json={"team_id": team_id, "key_alias": alias},
                    timeout=10,
                )
                if resp.status_code == 400 and "already exists" in resp.text:
                    # Key already exists — we can't retrieve its plaintext value
                    # from LiteLLM, so read it back from the repo's .env instead.
                    existing_key = _read_env_var(env_path, cfg["key_var"])
                    if not existing_key:
                        warn(f"  {client}: key exists but not in .env; delete and rerun to regenerate")
                        continue
                    api_key = existing_key
                    log(f"  {client}: key already exists, reusing from .env")
                else:
                    resp.raise_for_status()
                    api_key = resp.json().get("key")
                    if not api_key:
                        warn(f"  No key returned for {client}, skipping.")
                        continue
                    log(f"  {client}: key created")
            except requests.RequestException as e:
                warn(f"  Failed to create key for {client}: {e}")
                continue

            base_value = cfg.get("base_value", f"{GATEWAY_API_URL}{cfg['base_path']}")
            env_vars.append((cfg["base_var"], base_value))
            env_vars.append((cfg["key_var"], api_key))

            if client == "codex":
                _setup_codex_gateway_home(repo_dir)
                # OPENAI_BASE_URL was the old codex routing var; CODEX_HOME replaces it.
                stale_vars.append("OPENAI_BASE_URL")
            elif client == "gemini":
                _setup_gemini_trust(repo_dir)

        if env_vars:
            safe_update_env(env_path, env_vars, remove_vars=stale_vars)
            log(f"  Written {len(env_vars)//2} client configs to {env_path}")
            if stale_vars:
                log(f"  Removed stale vars: {', '.join(stale_vars)}")
            ensure_gitignore(repo_dir)

        log(f"  Done: {repo}")

    _ensure_bashrc_wrapper()
    log("\nAll repos processed.")

if __name__ == "__main__":
    main()
