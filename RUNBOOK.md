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

## Re-Authentication

OAuth tokens auto-refresh while the container is running. If you see 401s or a provider shows stale `last_refresh` in `health`, re-authenticate:

```bash
./cliproxy-setup.sh login-claude       # re-auth Claude
./cliproxy-setup.sh login-codex        # re-auth ChatGPT/Codex
./cliproxy-setup.sh login-antigravity  # re-auth Antigravity
./cliproxy-setup.sh login-grok         # re-auth Grok
./cliproxy-setup.sh login-kimi         # re-auth Kimi
```

The running container detects new token files automatically (file watcher, no restart needed).

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
./cliproxy-setup.sh login-claude   # or login-codex / login-gemini
# Container picks up new token automatically within ~30s
```

### LiteLLM models out of date after config change
```bash
docker compose restart litellm
```

### Full stack restart (e.g. after server reboot)
```bash
cd ~/repos/ai-gateway
docker compose up -d
# Wait ~20s for LiteLLM DB migration, then:
./cliproxy-setup.sh health
```

---

## File Reference

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Full stack definition |
| `Dockerfile.cliproxy` | CLIProxyAPI container image |
| `litellm-config.yaml` | Model routing (auto-managed by sync-models) |
| `.env` | Secrets (keys, passwords) — never commit |
| `cliproxy-setup.sh` | Setup, auth, sync, health CLI |
| `~/.cliproxy/config.yaml` | CLIProxyAPI config (port, API key, management key) |
| `~/.cli-proxy-api/*.json` | OAuth token files (Claude, Codex, Gemini) |

---

## ⚠️ Terms of Service Notice

This setup uses consumer subscriptions (Claude Pro, ChatGPT Plus, Gemini) via automated relay, which **may violate provider Terms of Service**. Use for personal, local access only. High-volume use may trigger account suspension.
