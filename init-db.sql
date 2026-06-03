CREATE DATABASE langfuse;
CREATE DATABASE litellm;

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

-- Create credential inventory table
CREATE TABLE IF NOT EXISTS credential_inventory (
    credential_id VARCHAR(255) PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,
    label VARCHAR(255),
    key_fingerprint VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'HEALTHY',
    cool_down_until TIMESTAMP WITH TIME ZONE,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- Ensure mcp_readonly can select from it immediately
GRANT SELECT ON TABLE credential_inventory TO mcp_readonly;
