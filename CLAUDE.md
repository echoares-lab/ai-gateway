# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session Workflow (quick reference)

Every session: **worktree → dev stack → code → unit test → commit → E2E test → PR to main → E2E test main → cleanup**

Full workflow details are in `AGENTS.md`. This file has the deep-dive on commands, architecture, and edge cases.

Process and PR-handling references:
- `REPO_IMPROVEMENT_WORKFLOW.md` — process rules.
- `REPO_IMPROVEMENT_APPENDIX.md` — repo-specific branch, env, and test commands.
- `AGENT_DISPATCH.md` — agent dispatch prompt for claim → implement → PR → auto-merge → closeout.
- `packages/repo-improvement-kit/` — portable kit source and deployment guide.

## Development Workflow (REQUIRED)

**Always work in a git worktree + dev stack — never edit the stable stack on port 4000 directly.**

```bash
# 1. Create a feature worktree (pick any free slot; slot 0 is the stable stack)
git worktree add ../ai-gateway-<feature> -b feat/<feature>
ln -s /home/dev/repos/ai-gateway/.env /home/dev/repos/ai-gateway-<feature>/.env
cd /home/dev/repos/ai-gateway-<feature>

# 2. Start an isolated dev stack in a free slot (use `./dev-env.sh list` to find one)
./dev-env.sh start 1          # or slot 2, 3, …

# 3. Edit code — hot-reload is automatic
# translator.py changes: uvicorn auto-reloads within ~1s
# litellm-config.yaml changes: litellm-reloader restarts LiteLLM within ~10s
# (no rebuild or manual restart needed)

# 4. Run unit tests (no container restart needed)
docker exec aidev1-translator-1 pytest test_translator.py -v

# 5. Run integration tests against the slot
./dev-env.sh test 1

# 6. When all tests pass, commit in the worktree and merge/PR to main
git add -p && git commit -m "..."
# Then from the main repo: git merge feat/<feature> (or open a PR)

# 7. Tear down and remove worktree
./dev-env.sh stop 1
cd /home/dev/repos/ai-gateway && git worktree remove ../ai-gateway-<feature>
```

## Common Commands

```bash
# Start full stack
docker compose up -d

# translator.py changes: no action needed, uvicorn auto-reloads
# (only rebuild needed if Dockerfile or dependencies change)
docker compose build translator && docker compose up -d translator

# litellm-config.yaml changes: automatic via litellm-reloader sidecar
# (no action needed; litellm-reloader watches and restarts LiteLLM)
# If you need to force restart: docker compose restart litellm

# Health check
./cliproxy-setup.sh health

# Test a specific model end-to-end
./cliproxy-setup.sh test claude-sonnet-4-6

# Probe all CLIProxy models and sync litellm-config.yaml
./cliproxy-setup.sh sync-models

# Quota summary: per-provider usage counts from CLIProxy
./cliproxy-setup.sh quota-summary

# Run translator unit tests (no container restart needed)
docker compose exec translator pytest test_translator.py -v

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

**`services/translator/translator.py`** is the real entry point — clients hit port 4000 which is the translator, not LiteLLM directly. LiteLLM is only accessible internally (and on port 4001 for its UI). The translator does three things:
1. **Responses API → Chat Completions**: Cursor Agent mode sends `input` (not `messages`) using OpenAI Responses API format. The translator converts all item types: plain `{role,content}` dicts, `function_call`, `function_call_output`, and content types like `input_text`/`input_image`.
2. **Tool format normalisation**: Cursor sends `{type, name, parameters}` (Responses API); LiteLLM needs `{type, function: {name, parameters}}` (Chat Completions).
3. **Model prefix**: `/v1/models` responses are prefixed with `AI-Gateway:` so Cursor can distinguish gateway models from its built-ins. The prefix is stripped from incoming requests before forwarding.

**`litellm-config.yaml`** defines all models. Every model routes through CLIProxy using the `openai/` provider prefix (CLIProxy is OpenAI-compatible) with `api_base: http://cliproxy:8317/v1`. Model aliases use dashes instead of dots (`gpt-5-4` not `gpt-5.4`) for LiteLLM compatibility; the `model:` field under `litellm_params` uses the original dotted name that CLIProxy expects.

**Redis caching** is enabled in `litellm_settings`. Only non-streaming requests are cached (LiteLLM limitation).

**Translator env vars** (all optional, set in `.env`):
| Variable | Default | Purpose |
|---|---|---|
| `LITELLM_URL` | `http://litellm:4000` | Internal LiteLLM endpoint |
| `WEB_CONCURRENCY` | `1` | Number of uvicorn worker processes |
| `HTTPX_MAX_KEEPALIVE` | `20` | httpx connection pool keep-alive connections |
| `HTTPX_MAX_CONNECTIONS` | `100` | httpx connection pool max connections |

**Gemini Pro models** have `disable_background_health_check: true` — they have strict per-minute rate limits (~5 req/min) that health check polling exhausts.

**CPA-Manager** runs on port 18317 and provides a management UI plus persistent usage analytics (SQLite) for CLIProxy. On first visit to `http://localhost:18317/management.html`, a setup wizard asks for the CPA URL (`http://cliproxy:8317`) and the Management Key. After setup, the wizard does not appear again. The `Cli-Proxy-API-Management-Center` repo is no longer deployed separately — CPA-Manager embeds the same panel and adds the Usage Service. CLIProxy also serves the built-in panel at `http://localhost:8317/management.html` (since v6.0.19).

## Key Files

| File | Purpose |
|------|---------|
| `services/translator/translator.py` | FastAPI proxy: Responses API translation + model prefix |
| `services/translator/Dockerfile` | Builds the translator container |
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

## Dev Environment (Isolated Dev Stacks)

`dev-env.sh` manages isolated 3-container dev stacks (cliproxy from fork + litellm + translator) so multiple agents can develop and test features without touching the stable gateway on port 4000.

Each **slot N** maps to dedicated ports (slot 0 = stable, reserved):
| Service | Stable | Slot 1 | Slot 2 |
|---|---|---|---|
| translator | :4000 | :4010 | :4020 |
| litellm UI | :4001 | :4011 | :4021 |
| cliproxy | :8317 | :8327 | :8337 |

```bash
# One-time: create a feature worktree
git worktree add ../ai-gateway-feat-X -b feat/X
ln -s /home/dev/repos/ai-gateway/.env /home/dev/repos/ai-gateway-feat-X/.env

# From inside the worktree (or repo root for slot testing):
./dev-env.sh start 1          # build & start — translator:4010, litellm:4011, cliproxy:8327

# After editing translator.py:
./dev-env.sh rebuild 1        # rebuilds translator only (fast)

# After editing CLIProxyAPI fork:
cd /home/dev/repos/CLIProxyAPI && git pull
./dev-env.sh rebuild-cliproxy 1

# Run integration tests against dev slot:
./dev-env.sh test 1

# Tail all dev logs:
./dev-env.sh logs 1

# Show all running dev containers across slots:
./dev-env.sh list

# Tear down (removes auth volume):
./dev-env.sh stop 1

git worktree remove ../ai-gateway-feat-X
```

**Dev stack details:**
- CLIProxy is built from `/home/dev/repos/CLIProxyAPI` (`dev` branch) so our patches are included
- OAuth tokens are seeded into an isolated Docker volume from `~/.cli-proxy-api/` at `start`; writes never touch host auth files
- LiteLLM uses SQLite (disposable, no Postgres) and `DISABLE_CACHE=true`
- If tokens expire mid-session, `./dev-env.sh stop 1 && ./dev-env.sh start 1` re-seeds them
- Multiple agents can run slots 1, 2, 3… simultaneously — fully isolated networks

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
