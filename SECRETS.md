# AI Gateway Secrets Management

This project uses 1Password Connect for managing secrets.

## Quick Start

1. Export Connect token:
   ```bash
   export OP_CONNECT_TOKEN=$(cat /etc/op-connect/token)
   ```

2. Use with docker-compose:
   ```bash
   op run --server https://{connect-hostname}:8200 -- \
     docker-compose up
   ```

3. Or with individual commands:
   ```bash
   export OP_CONNECT_TOKEN=$(cat /etc/op-connect/token)
   docker-compose up
   # Secrets are resolved via op run in Dockerfile
   ```

## Required Secrets

| Name | Vault Path | Purpose |
|------|-----------|---------|
| LITELLM_MASTER_KEY | op://ai-gateway/prod/LITELLM_MASTER_KEY | LiteLLM authentication |
| OPENAI_API_KEY | op://ai-gateway/prod/OPENAI_API_KEY | OpenAI model access |
| ANTHROPIC_API_KEY | op://ai-gateway/prod/ANTHROPIC_API_KEY | Claude model access |
| LITELLM_DATABASE_URL | op://ai-gateway/prod/LITELLM_DATABASE_URL | PostgreSQL connection |

See `.env.op` for full list.

## Development Setup

For local development without Connect access:

1. Copy `.env.example` to `.env.local`
2. Fill in values manually (for testing only)
3. `.env.local` is gitignored and safe for local overrides

## Rotation & Updates

To rotate secrets:
1. Go to 1Password vault: `op://ai-gateway/prod/`
2. Update the secret value
3. Restart containers: `docker-compose restart`
4. Changes take effect immediately (no code changes needed)

## Troubleshooting

**"Cannot connect to 1Password Connect"**
- Check: `curl http://{connect-hostname}:8200/health`
- Verify: `OP_CONNECT_TOKEN` is set
- Check network: Firewall allows {connect-hostname}:8200

**"Secret not found"**
- Verify vault exists: `op vault list`
- Check item in vault: `op read op://ai-gateway/prod/SECRET_NAME`
- Ensure role has access (Dev/Prod/CI)
