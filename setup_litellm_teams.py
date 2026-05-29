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

# Maps each client to the env vars its CLI actually reads.
CLIENT_CONFIG = {
    "claude": {
        "base_var": "ANTHROPIC_BASE_URL",   # Claude CLI: ANTHROPIC_BASE_URL
        "key_var":  "ANTHROPIC_API_KEY",
        "base_path": "",                     # Claude CLI appends /v1/messages itself
    },
    "codex": {
        "base_var": "OPENAI_BASE_URL",       # Codex CLI uses OpenAI env vars
        "key_var":  "OPENAI_API_KEY",
        "base_path": "/v1",
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
            try:
                resp = requests.post(
                    f"{LITELLM_ADMIN_URL}/key/generate",
                    headers=headers,
                    json={"team_id": team_id, "key_alias": f"{repo}-{client}"},
                    timeout=10,
                )
                resp.raise_for_status()
                api_key = resp.json().get("key")
                if not api_key:
                    warn(f"  No key returned for {client}, skipping.")
                    continue
            except requests.RequestException as e:
                warn(f"  Failed to create key for {client}: {e}")
                continue

            cfg = CLIENT_CONFIG[client]
            env_vars.append((cfg["base_var"], f"{GATEWAY_API_URL}{cfg['base_path']}"))
            env_vars.append((cfg["key_var"], api_key))
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
