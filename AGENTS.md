# AGENTS.md

## Cursor Cloud specific instructions

### Overview

This is a Docker Compose-based AI Gateway stack. All services run as containers — there are no language-level dependency files (no `requirements.txt`, no `package.json`). See `CLAUDE.md` for common commands and architecture details; see `RUNBOOK.md` for operational procedures.

### Docker requirement

Docker must be running before any `docker compose` commands. In the Cloud Agent VM, Docker is installed with `fuse-overlayfs` storage driver and `iptables-legacy` (kernel compatibility). Start the daemon with `sudo dockerd &` if it is not already running, then verify with `docker info`.

### Starting the stack

```bash
docker compose up -d
```

All 11 services will start. The translator waits for LiteLLM's healthcheck to pass (DB migration ~20s) before accepting traffic — no manual wait needed.

### Key ports

| Service | Port | Notes |
|---------|------|-------|
| translator | 4000 | Public entry point for all client traffic |
| litellm | 4001 | Internal proxy (UI accessible here) |
| langfuse-web | 3000 | Observability UI |
| cliproxy | 8317 | OAuth relay to LLM providers |
| cpa-manager | 18317 | CLIProxy usage analytics UI |
| postgres | 5432 | localhost only |
| redis | 6379 | localhost only |

### Environment setup

- `.env` must exist (copy from `.env.example`); it is gitignored
- `~/.cliproxy/config.yaml` and `~/.cli-proxy-api/` must exist for the cliproxy container volume mounts
- Without OAuth tokens in `~/.cli-proxy-api/`, CLIProxy will start but report 0 clients — requests to LLM providers will fail with 502. This is expected in cloud VM environments without browser OAuth access.

### Linting

```bash
pip install ruff                                      # install first
ruff check services/translator/translator.py          # lint
ruff format --check services/translator/translator.py # format check
bash -n cliproxy-setup.sh                            # shell syntax
python3 -c "import yaml; yaml.safe_load(open('litellm-config.yaml'))"  # YAML validate
```

Note: pyright is not configured in this repo; use ruff for linting.

### Testing the translator

The translator is the main custom code. Test its three functions by sending requests to port 4000:
1. **Model prefix**: `GET /v1/models` returns model IDs prefixed with `AI-Gateway:`
2. **Responses API translation**: POST with `input` field (Responses API format) gets translated to `messages` (Chat Completions format)
3. **Tool normalization**: Responses API tool format `{type, name, parameters}` gets converted to `{type, function: {name, parameters}}`

Upstream 502 errors from CLIProxy are expected without OAuth tokens — the translator's job is to translate the request format, not to authenticate with providers.

### Rebuilding after code changes

- `services/translator/translator.py` changes: **no action needed** — uvicorn auto-reloads on save (~1s)
- `litellm-config.yaml` changes: **no action needed** — litellm-reloader sidecar detects changes and restarts LiteLLM (~10s)
- `services/translator/Dockerfile` or pip dependencies changes: `docker compose build translator && docker compose up -d translator`
- `Dockerfile.cliproxy` changes: `docker compose build cliproxy && docker compose up -d cliproxy`
