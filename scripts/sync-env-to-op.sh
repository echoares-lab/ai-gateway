#!/usr/bin/env bash
# Sync .env values into 1Password fields referenced by .env.op
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
ENV_OP="${ENV_OP:-$ROOT/.env.op}"
VAULT="${OP_VAULT:-ai-gateway}"
ITEM="${OP_ITEM:-dev-secrets}"

if [[ -f "${HOME}/.op-token" && -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${HOME}/.op-token"
  set +a
fi

if ! op whoami >/dev/null 2>&1; then
  echo "ERROR: 1Password CLI not signed in."
  echo "  Service account: set -a && source ~/.op-token && set +a"
  echo "  Personal account: eval \"\$(op signin)\""
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: missing $ENV_FILE"
  exit 1
fi

if ! op item get "$ITEM" --vault "$VAULT" >/dev/null 2>&1; then
  op item create --category=SecureNote --title="$ITEM" --vault="$VAULT" \
    "notesPlain=ai-gateway stack secrets (managed by sync-env-to-op.sh)"
fi

exec python3 - "$ENV_FILE" "$ENV_OP" "$VAULT" "$ITEM" <<'PY'
import re, subprocess, sys
from pathlib import Path

env_file, env_op, vault, item = sys.argv[1:5]
env = {}
for line in Path(env_file).read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip()

fields = []
for line in Path(env_op).read_text().splitlines():
    m = re.match(r"^([A-Z_]+)=op://", line)
    if m:
        fields.append(m.group(1))

def resolve(key):
    if key == "REDIS_URL":
        auth = env.get("REDIS_AUTH", "myredissecret")
        return f"redis://:{auth}@redis:6379"
    return env.get(key, "")

updated, skipped = [], []
for key in fields:
    val = resolve(key)
    if not val:
        skipped.append(key)
        continue
    print(f"Updating op://{vault}/{item}/{key} ...")
    r = subprocess.run(
        ["op", "item", "edit", item, "--vault", vault, f"{key}[password]={val}"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(1)
    updated.append(key)

print(f"✓ {len(updated)} fields synced to op://{vault}/{item}/")
if skipped:
    print(f"  Skipped {len(skipped)} empty fields: {', '.join(skipped)}")
PY
