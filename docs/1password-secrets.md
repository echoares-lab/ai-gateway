# 1Password Secrets Inventory

This repo uses `repo-ai-gateway` for repo-local credentials and shared platform vaults for credentials reused elsewhere. Commit only reference files such as `.env.op`; keep resolved `.env` files local and gitignored.

## Vaults and items

| Scope | Vault | Item | Notes |
| --- | --- | --- | --- |
| Runtime | `repo-ai-gateway` | `prod`, `ci`, `test`, `local-dev` | LiteLLM, gateway, Langfuse, backing stores, CLIProxy |
| Shared AI/tools | `platform-ai-providers` | `ai-provider-keys` | Provider and search API keys reused by other repos |
| Shared notifications | `platform-notifications` | `slack` | Alerting webhooks |
| Shared GitHub | `platform-github-runners` | `github-runners` | Runner and GitHub automation credentials |

## Inventory

| Variable | Classification | Required | Target reference |
| --- | --- | --- | --- |
| `LITELLM_MASTER_KEY` | secret | runtime | `op://repo-ai-gateway/prod/LITELLM_MASTER_KEY` |
| `LITELLM_DATABASE_URL`, `DATABASE_URL` | secret | runtime | `op://repo-ai-gateway/prod/<FIELD>` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | secret | runtime | `op://repo-ai-gateway/prod/<FIELD>` |
| `REDIS_URL`, `REDIS_AUTH` | secret | runtime | `op://repo-ai-gateway/prod/<FIELD>` |
| `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD` | secret | runtime | `op://repo-ai-gateway/prod/<FIELD>` |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | secret | runtime | `op://repo-ai-gateway/prod/<FIELD>` |
| `NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY` | secret | runtime | `op://repo-ai-gateway/prod/<FIELD>` |
| `LANGFUSE_INIT_*` | secret/sensitive config | runtime | `op://repo-ai-gateway/prod/<FIELD>` |
| `CLIPROXY_API_KEY`, `CLIPROXY_MANAGEMENT_KEY`, `CLIPROXY_AUTH_TAR_B64` | secret | runtime | `op://repo-ai-gateway/prod/<FIELD>` |
| `ADMIN_API_KEY`, `GATEWAY_ENGINE_ADMIN_KEY` | secret | runtime/admin | `op://repo-ai-gateway/prod/<FIELD>` |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | secret | optional live provider tests/runtime | `op://platform-ai-providers/ai-provider-keys/<FIELD>` |
| `BRAVE_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY`, `SERPER_API_KEY` | secret | optional MCP/search tools | `op://platform-ai-providers/ai-provider-keys/<FIELD>` |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | secret | optional GitHub MCP | `op://platform-github-runners/github-runners/GITHUB_PERSONAL_ACCESS_TOKEN` |
| `SLACK_WEBHOOK_URL` | secret | optional alerting | `op://platform-notifications/slack/SLACK_WEBHOOK_URL` |
| `POLICY_ENGINE_ENABLED`, `POLICY_ENGINE_WS_EVALUATE`, `POLICY_ENGINE_TIMEOUT_MS`, `CACHE_ENABLED`, `CACHE_TTL_SECONDS`, `TEAM_BUDGET_SNAPSHOT_ENABLED`, `BUDGET_*`, `WEB_CONCURRENCY`, `HTTPX_*` | plain config | no | Keep in `.env.example` or deployment config |
| `LITELLM_URL`, `LITELLM_ADMIN_URL`, `GATEWAY_ENGINE_URL`, `POLICY_ENGINE_URL` | sensitive config | runtime | `op://repo-ai-gateway/prod/<FIELD>` |

## Usage

Local/dev:

```bash
op run --env-file .env.op -- docker compose up
```

CI:

```yaml
- uses: 1password/load-secrets-action@v4
  with:
    export-env: true
  env:
    OP_SERVICE_ACCOUNT_TOKEN: ${{ secrets.OP_SERVICE_ACCOUNT_TOKEN }}
    LITELLM_MASTER_KEY: op://repo-ai-gateway/ci/LITELLM_MASTER_KEY
```

`GITHUB_TOKEN` is supplied by GitHub Actions. `OP_SERVICE_ACCOUNT_TOKEN` is the bootstrap credential for reading 1Password references, so store it as a GitHub environment/repo secret rather than inside `.env.op`.

## Maintenance

New secrets require a PR updating `.env.op` and this inventory. CI/service accounts should be read-only and limited to `repo-ai-gateway` plus the specific shared platform items needed by the job.
