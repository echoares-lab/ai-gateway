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

## Adding & Provisioning Secrets

The 1Password Connect server and its associated tokens are strictly **read-only** and are intended solely for applications to consume secrets at runtime. 

To programmatically create or update secrets during deployment, CI/CD, or administrative tasks, you must use a **1Password Service Account**.

### Best Practice: Service Accounts for CLI Automation

For automated provisioning via the 1Password CLI (`op`), the officially recommended approach is to use **1Password Service Accounts**. Service Accounts are purpose-built for infrastructure automation, support read/write operations, and do not consume user seats.

**Step 1: Authenticate with a Service Account**
1. Create a Service Account in the 1Password Web UI (**Developer** -> **Service Accounts**).
2. Grant it "Create, Update, and Delete" permissions for the target vault(s).
3. Export the provided token in your terminal or CI environment:
   ```bash
   export OP_SERVICE_ACCOUNT_TOKEN="<your-service-account-token>"
   ```

**Step 2: Create Secrets via CLI**
With the service account token exported, the `op` CLI will automatically use it to authenticate:
```bash
# Create an API Key or credential
op item create --category="API Credential" --title="My New Service Key" --vault="ai-gateway" credential="super-secret-value"

# Create a standard password
op item create --category="login" --title="Database Password" --vault="ai-gateway" password="db-password-123"
```

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