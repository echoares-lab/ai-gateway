# Consumer LLM Proxy — Runbook

Unified access to Claude Pro, ChatGPT Plus, and Gemini consumer accounts via LiteLLM.

**Stack**: CLIProxyAPI (Docker) → LiteLLM (Docker) → Langfuse (Docker)  
**API endpoint**: `http://localhost:4000`  
**LiteLLM master key**: in `.env` as `LITELLM_MASTER_KEY`  
**CLIProxyAPI key**: in `~/.cliproxy/config.yaml` under `api-keys`

---

## First-Time Setup

### Prerequisites
- Docker + Docker Compose installed
- Claude Pro/Max account
- ChatGPT Plus or Pro account
- Antigravity CLI installed (`curl -fsSL https://antigravity.google/cli/install.sh | bash`)
- Google account (Gemini / Antigravity)
- SSH port forwarding if on a remote server (see [OAuth on Remote Server](#oauth-on-remote-server))

### 1. Install binaries
```bash
./cliproxy-setup.sh install
```

### 2. Authenticate each provider
Each command opens a browser OAuth flow and stores a token in `~/.cli-proxy-api/`.

```bash
./cliproxy-setup.sh login-claude       # port 54545 callback
./cliproxy-setup.sh login-codex        # port 1455 callback
./cliproxy-setup.sh login-antigravity  # Google account / Antigravity
./cliproxy-setup.sh login-grok         # Grok / X Premium
./cliproxy-setup.sh login-kimi         # Kimi
```

> **On a remote server**: set up SSH port forwarding first — see [OAuth on Remote Server](#oauth-on-remote-server).

### 3. Build and start the full stack
```bash
docker compose build cliproxy
docker compose up -d
```

### 4. Sync model list
Probes every model and adds working ones to `litellm-config.yaml`:
```bash
./cliproxy-setup.sh sync-models
```

### 5. Verify
```bash
./cliproxy-setup.sh health
./cliproxy-setup.sh test claude-sonnet-4-6
```

---

## Day-to-Day Operations

### Check status
```bash
./cliproxy-setup.sh health
```
Shows: CLIProxyAPI reachability, per-provider token status, Docker container state.

### Unified admin status (read-only)
```bash
source .env && curl -s http://localhost:4000/admin/status \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" | jq .
```
Returns the `admin-console.v1` JSON contract (see `docs/ADMIN_CONSOLE_DATA_CONTRACT.md`)
with health, models, providers, routing, and config-drift panels aggregated from the
translator, `litellm-config.yaml`, `/metrics`, and (best-effort) `cliproxy-setup.sh health`.
Read-only and operator-local: it never mutates state and redacts secrets. Degraded sources
report `warning`/`unknown` rather than failing the response.

For a rendered view, open the read-only dashboard page in a browser:
`http://localhost:4000/admin/dashboard` (operator-local; it fetches `/admin/status` and renders
the panels plus links to the LiteLLM UI, CLIProxy management, and CPA-Manager).

### Credential Health Alert Webhook
The gateway supports real-time Slack alerting webhooks for credential state changes (e.g., shifts to `CRITICAL`, `DEGRADED`, or recovery to `HEALTHY`).

To configure the alerting webhook:
1. Obtain a Slack incoming webhook URL.
2. Add it to your `.env` file:
   ```bash
   SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
   ```
3. Restart the background services or prober to pick up the configuration.

### List available models
```bash
./cliproxy-setup.sh models       # from CLIProxyAPI
```
Or from LiteLLM (what clients see):
```bash
curl -s http://localhost:4000/v1/models \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  | python3 -c "import sys,json; [print(m['id']) for m in json.load(sys.stdin)['data']]"
```

### Test a model
```bash
./cliproxy-setup.sh test claude-sonnet-4-6
./cliproxy-setup.sh test gemini-2-5-pro
./cliproxy-setup.sh test gpt-5-4
```

### Managing MCP (Model Context Protocol) Servers

MCP servers are configured globally under the `litellm_settings.mcp_servers` section of `litellm-config.yaml`. The AI Gateway supports standard `stdio` subprocess executions and remote `HTTP/SSE` endpoints.

#### Adding an MCP Server
To register a new `stdio` or `HTTP/SSE` MCP server:
1. Open `litellm-config.yaml` and locate the `mcp_servers:` block.
2. Add your new server entry under the block:
   ```yaml
   mcp_servers:
     my-custom-mcp-server:
       command: "npx" # Or "uvx" / "python3"
       args: ["-y", "@user/my-mcp-server-package", "--arg1", "val1"]
   ```
3. Restart LiteLLM to load the new server tools:
   ```bash
   docker compose restart litellm
   ```

#### Removing an MCP Server
To delete an MCP server:
1. Open `litellm-config.yaml` and delete the corresponding server block from under `mcp_servers:`.
2. Restart LiteLLM:
   ```bash
   docker compose restart litellm
   ```

#### Rotating Search & GitHub MCP API Keys & Health Check
Search and development MCP servers (such as `mcp-brave`, `mcp-tavily`, and `mcp-github`) dynamically consume upstream credentials configured in the shared `.env` file (`BRAVE_API_KEY`, `TAVILY_API_KEY`, `GITHUB_PERSONAL_ACCESS_TOKEN`).

To rotate keys or set up your GitHub integration safely:
1. Generate a GitHub Personal Access Token (PAT) with `repo` and `read:org` permissions.
2. Edit the secret variables inside your gitignored `.env` file:
   ```bash
   BRAVE_API_KEY="new-brave-key"
   TAVILY_API_KEY="new-tavily-key"
   GITHUB_PERSONAL_ACCESS_TOKEN="your-github-pat"
   ```
3. Restart the LiteLLM container to pick up the updated environment variables:
   ```bash
   docker compose up -d litellm
   ```
4. To check tool availability and search/GitHub health, inspect LiteLLM container logs:
   ```bash
   docker compose logs litellm | grep -i "mcp"
   ```

### View logs
```bash
docker compose logs cliproxy -f      # CLIProxyAPI logs
docker compose logs litellm -f       # LiteLLM proxy logs
docker compose logs langfuse-web -f  # Langfuse UI logs
```

---

## Management UI (CLIProxyAPI Web Dashboard)

CLIProxyAPI ships a built-in web UI at `/management.html` since v6.0.19.

**URL**: `http://<server-ip>:8317/management.html`  
**Management key**: stored in `~/.cliproxy/config.yaml` under `management-key`

> This key is separate from the `api-keys` list used by LiteLLM. Keep it private.

### What the UI provides

| Page | What it shows |
|------|---------------|
| Dashboard | Connection status, server version, model count snapshot |
| Config Panel | Visual editor for `config.yaml` with YAML diff preview on save |
| AI Providers | Per-provider key/URL/alias settings |
| Auth Files | Upload/download/delete OAuth token JSON files, view supported models per credential |
| OAuth | Start OAuth/device flows for Claude, Codex, Gemini, Grok, Kimi without the CLI |
| Quota Management | Quota limits and usage per provider |
| Logs | Tail logs with search, auto-refresh, hide management traffic |
| System | Update check, model list (`/v1/models`), local login data cleanup |

### Connecting

1. Open `http://<server-ip>:8317/management.html` in a browser
2. Enter the management key from `~/.cliproxy/config.yaml`
3. The address field auto-detects from the page URL — override if needed

### Security note

Port 8317 is now exposed on `0.0.0.0` (all interfaces). On a shared or public network, consider firewalling this port to trusted IPs only, or reverting to `127.0.0.1:8317:8317` in `docker-compose.yml` and using SSH forwarding:

```bash
ssh -L 8317:127.0.0.1:8317 dev@10.10.10.52 -p 22
# then open http://localhost:8317/management.html locally
```

---

## Per-Account Outbound Proxy

Each OAuth credential can route its outbound traffic through a different proxy. Useful when running multiple accounts from the same provider under different IP addresses.

**How it works**: CLIProxy reads `proxy_url` from each credential JSON file. When set it takes priority over the global `proxy-url` in `~/.cliproxy/config.yaml`. Supported schemes: `socks5://`, `socks5h://`, `http://`, `https://`, or `direct` (bypass any global proxy).

Priority chain: per-credential `proxy_url` → global `proxy-url` in config → `HTTPS_PROXY` env var → direct.

### Set via management API

Persists to the credential file immediately; no restart needed.

```bash
source .env
curl -X PATCH "http://localhost:8317/v0/management/auth-files/fields" \
  -H "X-Management-Key: $CLIPROXY_MANAGEMENT_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"antigravity-account@gmail.com.json","proxy_url":"socks5://proxy1:1080"}'
```

Clear a proxy assignment by setting `proxy_url` to `""`.

### Set by editing the credential file directly

CLIProxy hot-reloads on file change (~30s):

```bash
# e.g. ~/.cli-proxy-api/claude-firetvstream@gmail.com.json
{
  "email": "firetvstream@gmail.com",
  "type": "claude",
  "proxy_url": "socks5://proxy2:1080",
  ...
}
```

### List current assignments

```bash
source .env
curl -s "http://localhost:8317/v0/management/auth-files" \
  -H "X-Management-Key: $CLIPROXY_MANAGEMENT_KEY" \
  | python3 -c "
import sys, json
for f in json.load(sys.stdin).get('files', []):
    proxy = f.get('proxy_url') or '(none)'
    print(f['id'], '->', proxy)
"
```

### Credential filenames

| File | Provider |
|------|----------|
| `antigravity-{email}.json` | Google Antigravity (Gemini OAuth) |
| `claude-{email}.json` | Anthropic Claude OAuth |
| `codex-{email}-plus.json` | OpenAI Codex OAuth |
| `gemini-{email}-{project}.json` | Gemini CLI OAuth |

---

## Update Workflow

Run this whenever CLIProxyAPI releases a new version or you want to sync new models:

```bash
./cliproxy-setup.sh apply
```

This does three things in sequence:
1. **upgrade** — checks for a newer CLIProxyAPI release; rebuilds the Docker image if found
2. **sync-models** — probes all models from CLIProxyAPI; adds new working ones, removes dead ones from `litellm-config.yaml`; restarts LiteLLM if changed
3. **health** — prints current status

Or run steps individually:
```bash
./cliproxy-setup.sh upgrade       # check/apply CLIProxyAPI binary update
./cliproxy-setup.sh sync-models   # probe and update model list
./cliproxy-setup.sh health        # status check
```

---

## Upgrading CLIProxyAPI and CPA-Manager

Maintainers should periodically check for new releases and pin them in the repo to ensure stability.

### 1. Check for new releases
- **CLIProxyAPI**: [GitHub Releases](https://github.com/router-for-me/CLIProxyAPI/releases)
- **CPA-Manager**: [Docker Hub](https://hub.docker.com/r/seakee/cpa-manager/tags) or [GitHub Releases](https://github.com/seakee/cpa-manager/releases)

### 2. Update version pins
- **CLIProxyAPI**: Update `ARG CLIPROXY_VERSION` in `Dockerfile.cliproxy`.
- **CPA-Manager**: Update the `image: seakee/cpa-manager:<version>` tag in `docker-compose.yml`, `docker-compose.dev.yml`, and `docker-compose.mock.yml`.

### 3. Build and Validate
```bash
# Rebuild images with new versions
docker compose build cliproxy cpa-manager

# Start the stack
docker compose up -d

# Run health checks
./cliproxy-setup.sh health

# Test model routing
./cliproxy-setup.sh test gemini-3-flash
```

---

## Upgrading LiteLLM

LiteLLM should be kept up to date to support new models (OpenAI o1, Gemini 3.x) and performance features (Granian engine).

### 1. Find the latest stable version
Visit the [LiteLLM Releases page](https://github.com/BerriAI/litellm/releases) and identify the latest stable tag (e.g., `v1.87.1`). Avoid `-rc` or `-alpha` versions.

### 2. Get the SHA256 digest
To ensure deployment reproducibility and security, always pin the image by its SHA256 digest. You can find this on the [GitHub Container Registry](https://github.com/BerriAI/litellm/pkgs/container/litellm/versions) or by pulling the image locally:
```bash
docker pull ghcr.io/berriai/litellm:v1.87.1
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/berriai/litellm:v1.87.1
```

### 3. Update version pins
Update the `image:` tag in `docker-compose.yml` and `docker-compose.dev.yml`:
```yaml
image: ghcr.io/berriai/litellm:v1.87.1@sha256:9de3328...
```

### 4. Build and Validate
```bash
docker compose up -d litellm
./cliproxy-setup.sh health
./cliproxy-setup.sh test claude-sonnet-4-6
```

---

## Re-Authentication

OAuth tokens auto-refresh while the container is running. If you see 401s or a provider shows stale `last_refresh` in `health`, re-authenticate:

```bash
./cliproxy-setup.sh login-claude       # re-auth Claude
./cliproxy-setup.sh login-codex        # re-auth ChatGPT/Codex
./cliproxy-setup.sh login-antigravity  # re-auth Gemini / Antigravity (see migration below)
./cliproxy-setup.sh login-grok         # re-auth Grok
./cliproxy-setup.sh login-kimi         # re-auth Kimi
```

The running container detects new token files automatically (file watcher, no restart needed).

### ⚠️ Gemini CLI Sunset — June 18, 2026

**Gemini CLI OAuth tokens stop working June 18, 2026.** All Gemini models must migrate to Antigravity CLI.

**Migration steps:**
1. **Install Antigravity CLI** (if not already installed):
   ```bash
   curl -fsSL https://antigravity.google/cli/install.sh | bash
   ```

2. **Authenticate with Antigravity** (replaces Gemini CLI):
   ```bash
   ./cliproxy-setup.sh login-antigravity
   ```

3. **Verify Gemini models work:**
   ```bash
   ./cliproxy-setup.sh test gemini-3-1-pro
   ./cliproxy-setup.sh test gemini-3-flash
   ```

4. **After June 18, 2026:** Any remaining Gemini CLI tokens will be rejected. Ensure all systems use `login-antigravity`.

---

## OAuth on Remote Server

The OAuth callback URLs (`localhost:PORT`) go to your **local browser**, not the server. You need SSH port forwarding so the browser's localhost traffic tunnels to the server.

**Open a new local terminal and SSH with port forwards:**
```bash
ssh -L 54545:localhost:54545 \
    -L 1455:localhost:1455 \
    -L 8085:localhost:8085 \
    user@your-server
```

Then run login commands from that forwarded session:
```bash
./cliproxy-setup.sh login-all
```

**Headless alternative** (no browser, paste the redirect URL manually):
```bash
./cliproxy-setup.sh login-headless claude
./cliproxy-setup.sh login-headless codex
./cliproxy-setup.sh login-headless antigravity
./cliproxy-setup.sh login-headless grok
./cliproxy-setup.sh login-headless kimi
```

---

## Connecting Clients

### Bootstrap a repo with tenant-aware keys (epic #30)

```bash
setup-repo-env.sh --org echoares --workspace core --team eng --env dev /path/to/your-repo
```

Writes `.envrc` + isolated `CODEX_HOME`. Expected LiteLLM virtual key label:
`ak-{org}-{workspace}-{team}-{repo}-{environment}`. See [docs/TENANCY.md](./docs/TENANCY.md).

### Generate config snippets

Print ready-to-paste connection settings for any supported client profile
(no secrets are read or written — the key is always a placeholder you substitute):

```bash
./gen-client-config.sh all --org echoares --workspace core --team eng --repo my-app --env dev
./gen-client-config.sh cursor --base-url http://localhost:4000
./gen-client-config.sh gemini --key-var MY_KEY
```

Clients: `cursor`, `claude-code`, `codex`, `gemini`, `openai-sdk`, `all`.
Profiles are sourced from [docs/CLIENT_COMPATIBILITY.md](./docs/CLIENT_COMPATIBILITY.md) §2.

### Cursor
Settings → Models → Custom:
- **Base URL**: `http://your-server:4000`
- **API Key**: value of `LITELLM_MASTER_KEY` from `.env`
- Pick any model from the list (e.g. `claude-sonnet-4-6`)

### Python (OpenAI SDK)
```python
import openai

client = openai.OpenAI(
    api_key="<LITELLM_MASTER_KEY>",
    base_url="http://localhost:4000"
)

response = client.chat.completions.create(
    model="claude-sonnet-4-6",   # or any model from the list
    messages=[{"role": "user", "content": "Hello"}]
)
print(response.choices[0].message.content)
```

### LiteLLM Python SDK
```python
import litellm

response = litellm.completion(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "Hello"}],
    api_key="<LITELLM_MASTER_KEY>",
    api_base="http://localhost:4000"
)
```

### curl
```bash
curl -s -X POST http://localhost:4000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -d '{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"Hello"}]}'
```

---

## Available Models

Run `./cliproxy-setup.sh models` for the live list. Typical roster:

| Alias | Provider | Account |
|-------|----------|---------|
| `claude-opus-4-7` | Anthropic | Claude Pro/Max |
| `claude-sonnet-4-6` | Anthropic | Claude Pro/Max |
| `claude-opus-4-6` | Anthropic | Claude Pro/Max |
| `claude-opus-4-5` | Anthropic | Claude Pro/Max |
| `claude-sonnet-4-5` | Anthropic | Claude Pro/Max |
| `claude-haiku-4-5` | Anthropic | Claude Pro/Max |
| `claude-opus-4-1` | Anthropic | Claude Pro/Max |
| `gpt-5-5` | OpenAI | ChatGPT Plus/Pro |
| `gpt-5-4` | OpenAI | ChatGPT Plus/Pro |
| `gpt-5-4-mini` | OpenAI | ChatGPT Plus/Pro |
| `gpt-5-3-codex` | OpenAI | ChatGPT Plus/Pro |
| `gpt-5-2` | OpenAI | ChatGPT Plus/Pro |
| `gemini-3-1-pro` | Google | Google account |
| `gemini-3-pro` | Google | Google account |
| `gemini-3-flash` | Google | Google account |
| `gemini-2-5-pro` | Google | Google account |
| `gemini-2-5-flash` | Google | Google account |
| `gemini-2-5-flash-lite` | Google | Google account |

---

## Troubleshooting

### CLIProxyAPI not reachable
```bash
docker compose ps cliproxy
docker compose logs cliproxy --tail=20
docker compose restart cliproxy
```

### LiteLLM returning 500 / connection errors
```bash
docker compose logs litellm --tail=20
# Check cliproxy is running first:
./cliproxy-setup.sh health
```

### Model returns 503 ServiceUnavailableError
The model exists in CLIProxyAPI's list but isn't active. Run:
```bash
./cliproxy-setup.sh sync-models   # removes dead models automatically
```

### Token expired / 401 from a provider
```bash
./cliproxy-setup.sh login-claude       # or login-codex / login-antigravity / login-grok / login-kimi
# Container picks up new token automatically within ~30s
```

**For Gemini models:** Use `login-antigravity` (Gemini CLI deprecated; see [Gemini CLI Sunset](#-gemini-cli-sunset--june-18-2026))

### LiteLLM models out of date after config change
```bash
docker compose restart litellm
```

### Full stack restart (e.g. after server reboot)
```bash
cd ~/repos/ai-gateway
docker compose up -d
# LiteLLM healthcheck gates the translator startup — no manual wait needed
./cliproxy-setup.sh health
```

---

## File Reference

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Full stack definition |
| `services/translator/translator.py` | FastAPI proxy — Responses API translation + model prefix |
| `services/translator/Dockerfile` | Builds the translator container |
| `services/translator/gemini-model-map.json` | Dotted→dashed Gemini model alias map (auto-managed by sync-models) |
| `Dockerfile.cliproxy` | Builds the CLIProxyAPI container image |
| `docs/ARCHITECTURE.md` | Architecture Decision Record (ADR) — MCP Control Plane Hosting |
| `litellm-config.yaml` | Model routing (auto-managed by sync-models) |
| `.env` | Secrets (keys, passwords) — never commit |
| `cliproxy-setup.sh` | Setup, auth, sync, health CLI |
| `~/.cliproxy/config.yaml` | CLIProxyAPI config (port, API key, management key) |
| `~/.cli-proxy-api/*.json` | OAuth token files (Claude, Codex, Gemini) |

---

## ⚠️ Terms of Service Notice

This setup uses consumer subscriptions (Claude Pro, ChatGPT Plus, Gemini) via automated relay, which **may violate provider Terms of Service**. Use for personal, local access only. High-volume use may trigger account suspension.
