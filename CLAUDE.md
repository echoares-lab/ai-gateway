# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

```bash
# Start full stack
docker compose up -d

# Rebuild and restart translator only (after translator.py changes)
docker compose build translator && docker compose up -d translator

# Restart LiteLLM only (after litellm-config.yaml changes)
docker compose restart litellm

# Health check
./cliproxy-setup.sh health

# Test a specific model end-to-end
./cliproxy-setup.sh test claude-sonnet-4-6

# Probe all CLIProxy models and sync litellm-config.yaml
./cliproxy-setup.sh sync-models

# View logs
docker compose logs translator -f
docker compose logs litellm -f
docker compose logs cliproxy -f

# Redis cache health
source .env && curl -s http://localhost:4000/cache/ping -H "Authorization: Bearer $LITELLM_MASTER_KEY" | jq .

# List models as clients see them
source .env && curl -s http://localhost:4000/v1/models -H "Authorization: Bearer $LITELLM_MASTER_KEY" | python3 -c "import sys,json; [print(m['id']) for m in json.load(sys.stdin)['data']]"
```

## Architecture

```
External client (Cursor, curl, SDK)
  └─► Cloudflare Tunnel (ai.plexplease.com) → 10.10.10.52:4000
        └─► translator (port 4000, public)   ← entry point for ALL traffic
              └─► litellm (port 4000 internal, 4001 external for UI)
                    └─► cliproxy (port 8317)
                          ├─► Anthropic (Claude Pro/Max OAuth)
                          ├─► OpenAI (ChatGPT Plus/Pro OAuth)
                          ├─► Google Antigravity (Gemini OAuth)
                          ├─► xAI (Grok OAuth)
                          └─► Moonshot (Kimi OAuth)
```

**`translator.py`** is the real entry point — clients hit port 4000 which is the translator, not LiteLLM directly. LiteLLM is only accessible internally (and on port 4001 for its UI). The translator does three things:
1. **Responses API → Chat Completions**: Cursor Agent mode sends `input` (not `messages`) using OpenAI Responses API format. The translator converts all item types: plain `{role,content}` dicts, `function_call`, `function_call_output`, and content types like `input_text`/`input_image`.
2. **Tool format normalisation**: Cursor sends `{type, name, parameters}` (Responses API); LiteLLM needs `{type, function: {name, parameters}}` (Chat Completions).
3. **Model prefix**: `/v1/models` responses are prefixed with `AI-Gateway:` so Cursor can distinguish gateway models from its built-ins. The prefix is stripped from incoming requests before forwarding.

**`litellm-config.yaml`** defines all models. Every model routes through CLIProxy using the `openai/` provider prefix (CLIProxy is OpenAI-compatible) with `api_base: http://cliproxy:8317/v1`. Model aliases use dashes instead of dots (`gpt-5-4` not `gpt-5.4`) for LiteLLM compatibility; the `model:` field under `litellm_params` uses the original dotted name that CLIProxy expects.

**Redis caching** is enabled in `litellm_settings`. Only non-streaming requests are cached (LiteLLM limitation).

**Gemini Pro models** have `disable_background_health_check: true` — they have strict per-minute rate limits (~5 req/min) that health check polling exhausts.

## Key Files

| File | Purpose |
|------|---------|
| `translator.py` | FastAPI proxy: Responses API translation + model prefix |
| `Dockerfile.translator` | Builds the translator container |
| `litellm-config.yaml` | All model definitions (auto-managed by `sync-models`) |
| `cliproxy-setup.sh` | Auth, sync, health, upgrade CLI |
| `.env` | All secrets — gitignored, never commit |
| `.env.example` | Template for `.env` |
| `init-db.sql` | Creates `litellm` database on first postgres start |

## Working in Worktrees

Feature work goes in git worktrees to avoid branch-switching in the main dir:

```bash
git worktree add ../ai-gateway-<feature> -b feat/<feature>
# Symlink .env so secrets are available
ln -s /home/dev/repos/ai-gateway/.env /home/dev/repos/ai-gateway-<feature>/.env
```

Run `docker compose` from within the worktree directory when testing changes there. The compose project name is `ai` (set in `docker-compose.yml`) — running from two worktrees simultaneously will conflict on container names.

## Cursor Integration

- **Base URL**: `https://ai.plexplease.com/v1`
- **Model names**: Must use `AI-Gateway:` prefix, e.g. `AI-Gateway:claude-sonnet-4-6`
- The prefix is added by the translator's `/v1/models` response and stripped before forwarding to LiteLLM — no changes to `litellm-config.yaml` needed for new models.

## LiteLLM Database

LiteLLM stores virtual keys, team settings, and tool configs in Postgres. Changes made via the LiteLLM UI or API are persisted there and take precedence over `litellm-config.yaml`. If a config change doesn't seem to take effect, check the database:

```bash
docker exec -it ai-postgres-1 psql -U postgres -d litellm
```

Notable: `search_tools` and MCP tool configs live in `LiteLLM_ToolTable` / `LiteLLM_SearchToolsTable`. These have caused issues before (intercepting tool-bearing requests). If Cursor Agent mode starts 500-ing, check these tables.
