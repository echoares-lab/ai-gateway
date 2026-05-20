# Model Reference — Consumer LLM Proxy

All models route through CLIProxyAPI (OAuth relay) → LiteLLM on `http://localhost:4000`.
No API billing. Limits are consumer subscription quotas, not API tier limits.

---

## Stack Overview

```
Client (Cursor / Python / curl)
  └─► LiteLLM  :4000   (OpenAI-compatible API, model routing, Langfuse logging)
        └─► CLIProxyAPI  :8317  (OAuth relay, token auto-refresh every 15 min)
              ├─► Anthropic  (Claude Pro/Max account)
              ├─► OpenAI     (ChatGPT Plus/Pro account)
              ├─► Google     (Gemini Advanced / Google account)
              ├─► xAI        (Grok / X Premium account)
              └─► Moonshot   (Kimi account)
```

API endpoint: `http://localhost:4000`  
Auth header: `Authorization: Bearer <LITELLM_MASTER_KEY>` (see `.env`)

---

## Claude Models (Anthropic — Claude Pro/Max subscription)

**Auth**: OAuth via Claude Code login. Token lifetime: ~8h access token, auto-refreshed from refresh token stored in `~/.cli-proxy-api/claude-*.json`.

**Rate limits** (Claude Pro): Rolling 5-hour usage window, not a hard daily count. Resets continuously.

| Alias | Upstream model ID | Tier | ~Msgs per 5h window |
|-------|-------------------|------|---------------------|
| `claude-opus-4-7` | `claude-opus-4-7` | Flagship Opus | 10–20 |
| `claude-opus-4-6` | `claude-opus-4-6` | Opus | 10–20 |
| `claude-sonnet-4-6` | `claude-sonnet-4-6` | Sonnet | 50–100 |
| `claude-opus-4-5` | `claude-opus-4-5-20251101` | Opus | 10–20 |
| `claude-sonnet-4-5` | `claude-sonnet-4-5-20250929` | Sonnet | 50–100 |
| `claude-haiku-4-5` | `claude-haiku-4-5-20251001` | Haiku | 200+ |
| `claude-opus-4-1` | `claude-opus-4-1-20250805` | Opus | 10–20 |

**Versioned aliases** (added by sync-models, kept for client compatibility):
`claude-sonnet-4-5-20250929`, `claude-haiku-4-5-20251001`, `claude-opus-4-5-20251101`, `claude-opus-4-1-20250805`

**Health check notes**: Sonnet and Haiku are safe for background health checks. Opus models should have `disable_background_health_check: true` if health checks are enabled, as each probe consumes from the limited Opus quota.

**Claude Max (5× plan)** multiplies all message limits by ~5.

---

## OpenAI Models (ChatGPT Plus/Pro subscription)

**Auth**: OAuth via Codex login. Token lifetime: ~240h (~10 days) access token. Stored in `~/.cli-proxy-api/codex-*.json`.

**Rate limits**: Rolling 3-hour window. GPT-4 class models share a combined quota.

| Alias | Upstream model ID | Notes |
|-------|-------------------|-------|
| `gpt-5-5` | `gpt-5.5` | Flagship |
| `gpt-5-4` | `gpt-5.4` | |
| `gpt-5-4-mini` | `gpt-5.4-mini` | Higher limits than full GPT-5 |
| `gpt-5-3-codex` | `gpt-5.3-codex` | Reasoning/code focus |
| `gpt-5-2` | `gpt-5.2` | |
| `codex-auto-review` | `codex-auto-review` | Code review specialization |

**Approximate limits**: 50–80 messages per 3-hour window for GPT-4+ class. Mini/smaller variants have higher limits. ChatGPT Pro subscription has significantly higher caps than Plus.

**Health check notes**: All GPT models are safe for background health checks at the default 5-min interval.

---

## Gemini Models (Google account — Gemini Advanced subscription)

**Auth**: OAuth via Gemini CLI login. Token uses Google's `token`/`auto` auth fields (no explicit expiry). Stored in `~/.cli-proxy-api/gemini-*.json`. Token is refreshed by CLIProxyAPI's file watcher.

**Rate limits**: Strictest of all three providers. Per-day and per-minute caps enforced at the account level.

| Alias | Upstream model ID | Req/day | Req/min | Health check |
|-------|-------------------|---------|---------|--------------|
| `gemini-3-1-pro` | `gemini-3.1-pro-preview` | ~25–50 | ~5 | DISABLED |
| `gemini-3-1-pro-preview` | `gemini-3.1-pro-preview` | ~25–50 | ~5 | DISABLED |
| `gemini-3-pro` | `gemini-3-pro-preview` | ~25–50 | ~5 | DISABLED |
| `gemini-3-pro-preview` | `gemini-3-pro-preview` | ~25–50 | ~5 | DISABLED |
| `gemini-2-5-pro` | `gemini-2.5-pro` | ~25–50 | ~5 | DISABLED |
| `gemini-3-flash` | `gemini-3-flash-preview` | ~500–1000 | ~15 | enabled |
| `gemini-3-flash-preview` | `gemini-3-flash-preview` | ~500–1000 | ~15 | enabled |
| `gemini-3-1-flash-lite` | `gemini-3.1-flash-lite-preview` | ~1000+ | ~30 | enabled |
| `gemini-3-1-flash-lite-preview` | `gemini-3.1-flash-lite-preview` | ~1000+ | ~30 | enabled |
| `gemini-2-5-flash` | `gemini-2.5-flash` | ~500–1000 | ~15 | enabled |
| `gemini-2-5-flash-lite` | `gemini-2.5-flash-lite` | ~1000+ | ~30 | enabled |

**Health check notes**: All Gemini Pro variants have `disable_background_health_check: true` in `litellm-config.yaml`. Pro models 429 under normal health check frequency (~5 req/min limit, health checks fire every 5 min across 5+ Pro aliases = burst at interval boundary). Flash and Flash-Lite models are safe.

**429 behavior**: CLIProxyAPI returns 429 to LiteLLM, which logs it as a `ServiceUnavailableError`. Does not consume daily quota.

---

## xAI Models (Grok — X Premium/Premium+ subscription)

**Auth**: OAuth via xAI/X login. Stored in `~/.cli-proxy-api/grok-*.json`.

**Features**: Real-time access to X (Twitter) data and web search.

| Alias | Upstream model ID | Notes |
|-------|-------------------|-------|
| `grok-beta` | `grok-beta` | Latest experimental |
| `grok-2` | `grok-2` | |
| `grok-2-vision` | `grok-2-vision` | |

---

## Moonshot Models (Kimi)

**Auth**: OAuth via Kimi login. Stored in `~/.cli-proxy-api/kimi-*.json`.

**Features**: High-quality web search and long context support.

---

## Background Health Checks

Controlled in `litellm-config.yaml` under `general_settings` (currently **disabled** — commented out).

```yaml
general_settings:
  background_health_checks: true
  health_check_interval: 300      # seconds between full sweeps
  health_check_concurrency: 5     # max parallel probes
```

**What it sends per model**: One chat completion request — `"Hey how's it going?"` or `"What's 1+1?"` with `max_tokens: 1`. Roughly 6–7 input tokens, 1 output token.

**Cost at default settings** (300s interval, 30 models, Gemini Pro excluded):
- ~25 probes per cycle
- ~12 cycles/hour = ~300 probes/hour
- ~7,200 probes/day
- Token cost: negligible (consumer accounts, no billing)

**To enable**: Uncomment the three lines in `litellm-config.yaml` and restart:
```bash
docker compose restart litellm
```

**To disable health checks for a specific model**, add to its entry:
```yaml
model_info:
  disable_background_health_check: true
```

**Viewing results**: LiteLLM UI → Model Health page (port 4000/ui). The `/health` endpoint requires the master key:
```bash
curl -s http://localhost:4000/health \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```
The unauthenticated equivalent (no model probing, just liveness):
```bash
curl -s http://localhost:4000/health/readiness
```

---

## Token Lifetime Summary

| Provider | Access token | Refresh strategy |
|----------|-------------|-----------------|
| Claude | ~8 hours | CLIProxyAPI auto-refreshes from refresh token every 15 min |
| Codex/OpenAI | ~240 hours (~10 days) | Same — file watcher, 15-min refresh cycle |
| Gemini | No expiry field | Google CLI token; CLIProxyAPI watches for changes |

Re-authenticate if you see 401s from a provider:
```bash
./cliproxy-setup.sh login-claude    # port 54545 callback
./cliproxy-setup.sh login-codex     # port 1455 callback
./cliproxy-setup.sh login-gemini    # no fixed port
```

On a remote server, open SSH port forwards first (run locally):
```bash
ssh -L 54545:127.0.0.1:54545 -L 1455:127.0.0.1:1455 -L 8085:127.0.0.1:8085 dev@10.10.10.52 -p 22
```

---

## sync-models

`./cliproxy-setup.sh sync-models` probes every model CLIProxyAPI reports and:
- Adds new working models to `litellm-config.yaml`
- Removes models that return 503 (ServiceUnavailable)
- Restarts LiteLLM if the config changed

Run automatically as part of the weekly apply job:
```
0 3 * * 0  /home/dev/repos/test/cliproxy-setup.sh apply >> /home/dev/.cliproxy/apply.log 2>&1
```

Model aliases use dashes instead of dots (`gpt-5.4` → `gpt-5-4`) for LiteLLM compatibility. The upstream `model:` field preserves the original dotted name as CLIProxyAPI expects it.
