-- Mock CI Postgres bootstrap: databases and MCP read-only role only.
-- Do not create tables in the litellm database here; init-db.sql's
-- credential_inventory triggers Prisma P3005 and slow baseline resolution.

SELECT 'CREATE DATABASE langfuse' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
SELECT 'CREATE DATABASE litellm' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'litellm')\gexec

\c postgres;

DO
$do$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_readonly') THEN
      CREATE ROLE mcp_readonly WITH LOGIN PASSWORD 'mcp_readonly_secret';
   END IF;
END
$do$;

GRANT CONNECT ON DATABASE postgres TO mcp_readonly;
GRANT USAGE ON SCHEMA public TO mcp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_readonly;

GRANT CONNECT ON DATABASE litellm TO mcp_readonly;
