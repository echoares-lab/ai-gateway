-- Create databases conditionally using psql's \gexec
SELECT 'CREATE DATABASE langfuse' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
SELECT 'CREATE DATABASE litellm' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'litellm')\gexec

\c postgres;

-- Create read-only role for MCP Postgres server
DO
$do$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_readonly') THEN
      CREATE ROLE mcp_readonly WITH LOGIN PASSWORD 'mcp_readonly_secret';
   END IF;
END
$do$;

-- Grant basic connect/usage
GRANT CONNECT ON DATABASE postgres TO mcp_readonly;
GRANT USAGE ON SCHEMA public TO mcp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_readonly;

\c litellm;

-- Create credential inventory table in the LiteLLM database.
CREATE TABLE IF NOT EXISTS credential_inventory (
    credential_id text PRIMARY KEY,
    provider text NOT NULL CHECK (provider IN ('openai', 'anthropic', 'gemini', 'xai', 'moonshot', 'antigravity', 'gemini-cli', 'codex', 'claude')),
    label text NOT NULL,
    key_fingerprint text NOT NULL,
    status text NOT NULL DEFAULT 'HEALTHY' CHECK (status IN ('HEALTHY', 'DEGRADED', 'CRITICAL', 'EXPIRED', 'SUSPENDED')),
    cool_down_until timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION set_credential_inventory_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS credential_inventory_set_updated_at ON credential_inventory;
CREATE TRIGGER credential_inventory_set_updated_at
    BEFORE UPDATE ON credential_inventory
    FOR EACH ROW
    EXECUTE FUNCTION set_credential_inventory_updated_at();

CREATE INDEX IF NOT EXISTS credential_inventory_provider_status_idx
    ON credential_inventory (provider, status);

CREATE INDEX IF NOT EXISTS credential_inventory_cool_down_until_idx
    ON credential_inventory (cool_down_until)
    WHERE cool_down_until IS NOT NULL;

-- Ensure mcp_readonly can inspect credential health without write privileges.
GRANT CONNECT ON DATABASE litellm TO mcp_readonly;
GRANT USAGE ON SCHEMA public TO mcp_readonly;
GRANT SELECT ON TABLE credential_inventory TO mcp_readonly;
