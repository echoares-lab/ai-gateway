#!/usr/bin/env python3

"""
Automates setup of LiteLLM teams and API keys for each repository in a
GitHub organization. Creates one team per repo and one key per client,
then writes the correct env vars into each repo's .env file.

Requirements:
  - requests (`pip install requests`)
  - gh CLI (https://cli.github.com/) — logged in with repo read access
"""

import os
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

def safe_update_env(env_path, variables):
    """Replace named vars in env_path (or create it) with new values."""
    lines = open(env_path).readlines() if os.path.exists(env_path) else []
    var_names = {var for var, _ in variables}
    kept = [l for l in lines if l.split("=", 1)[0].strip() not in var_names]
    kept += [f"{var}={value}\n" for var, value in variables]
    with open(env_path, "w") as f:
        f.writelines(kept)

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

def _setup_codex_gateway_home(api_key: str):
    """
    Create ~/.codex-gateway/ with a config.toml that points openai_base_url at
    our gateway.  No auth.json is written — the absence of stored ChatGPT tokens
    causes Codex to fall back to OPENAI_API_KEY env-var API-key mode.

    Sourcing the repo .env before running Codex:
        source .env && codex exec "..."
    routes all inference through the gateway.  The user's default ~/.codex
    (ChatGPT OAuth) is untouched and still works when .env is not sourced.
    """
    os.makedirs(CODEX_GATEWAY_HOME, exist_ok=True)

    config_path = os.path.join(CODEX_GATEWAY_HOME, "config.toml")
    openai_base_url = f"{GATEWAY_API_URL}/v1"

    # Read existing config and replace/add openai_base_url.
    lines = open(config_path).readlines() if os.path.exists(config_path) else []
    kept = [l for l in lines if not l.strip().startswith("openai_base_url")]
    kept.append(f'openai_base_url = "{openai_base_url}"\n')
    with open(config_path, "w") as f:
        f.writelines(kept)

    log(f"  codex: wrote {config_path} (openai_base_url={openai_base_url})")


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

        for client in CLIENTS:
            alias = f"{repo}-{client}"
            try:
                resp = requests.post(
                    f"{LITELLM_ADMIN_URL}/key/generate",
                    headers=headers,
                    json={"team_id": team_id, "key_alias": alias},
                    timeout=10,
                )
                if resp.status_code == 400 and "already exists" in resp.text:
                    log(f"  {client}: key already exists, skipping")
                    continue
                resp.raise_for_status()
                api_key = resp.json().get("key")
                if not api_key:
                    warn(f"  No key returned for {client}, skipping.")
                    continue
            except requests.RequestException as e:
                warn(f"  Failed to create key for {client}: {e}")
                continue

            cfg = CLIENT_CONFIG[client]
            base_value = cfg.get("base_value", f"{GATEWAY_API_URL}{cfg['base_path']}")
            env_vars.append((cfg["base_var"], base_value))
            env_vars.append((cfg["key_var"], api_key))

            if client == "codex":
                _setup_codex_gateway_home(api_key)

            log(f"  {client}: key created")

        if env_vars:
            env_path = os.path.join(repo_dir, ".env")
            safe_update_env(env_path, env_vars)
            log(f"  Written {len(env_vars)//2} client configs to {env_path}")
            ensure_gitignore(repo_dir)

        log(f"  Done: {repo}")

    log("\nAll repos processed.")

if __name__ == "__main__":
    main()
