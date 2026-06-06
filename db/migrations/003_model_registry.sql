\connect litellm

CREATE TABLE IF NOT EXISTS model_registry (
    model_id text PRIMARY KEY,
    provider text NOT NULL CHECK (provider IN (
        'openai', 'anthropic', 'gemini', 'xai', 'moonshot',
        'antigravity', 'gemini-cli', 'codex', 'claude', 'unknown'
    )),
    family text NOT NULL DEFAULT 'unknown',
    upstream_model text NOT NULL,
    litellm_model text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    status text NOT NULL DEFAULT 'UNKNOWN' CHECK (status IN (
        'UNKNOWN', 'HEALTHY', 'DEGRADED', 'CRITICAL', 'DISABLED'
    )),
    supports_tools boolean,
    supports_vision boolean,
    max_input_tokens integer CHECK (max_input_tokens IS NULL OR max_input_tokens >= 0),
    max_output_tokens integer CHECK (max_output_tokens IS NULL OR max_output_tokens >= 0),
    cost_tier integer CHECK (cost_tier IS NULL OR cost_tier BETWEEN 1 AND 3),
    policy_metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(policy_metadata) = 'object'),
    probe_status text,
    probe_http_status integer,
    probe_checked_at timestamptz,
    source text NOT NULL DEFAULT 'manual',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_aliases (
    alias text PRIMARY KEY,
    model_id text NOT NULL REFERENCES model_registry(model_id) ON DELETE CASCADE,
    provider text NOT NULL,
    alias_kind text NOT NULL DEFAULT 'client',
    target text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_reconcile_runs (
    run_id bigserial PRIMARY KEY,
    action text NOT NULL,
    dry_run boolean NOT NULL DEFAULT true,
    status text NOT NULL,
    changed_resources jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(changed_resources) = 'array'),
    error text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION set_model_registry_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS model_registry_set_updated_at ON model_registry;
CREATE TRIGGER model_registry_set_updated_at
    BEFORE UPDATE ON model_registry
    FOR EACH ROW
    EXECUTE FUNCTION set_model_registry_updated_at();

DROP TRIGGER IF EXISTS model_aliases_set_updated_at ON model_aliases;
CREATE TRIGGER model_aliases_set_updated_at
    BEFORE UPDATE ON model_aliases
    FOR EACH ROW
    EXECUTE FUNCTION set_model_registry_updated_at();

CREATE INDEX IF NOT EXISTS model_registry_provider_status_idx
    ON model_registry (provider, status);

CREATE INDEX IF NOT EXISTS model_registry_enabled_idx
    ON model_registry (enabled);

CREATE INDEX IF NOT EXISTS model_aliases_model_id_idx
    ON model_aliases (model_id);

GRANT SELECT ON TABLE model_registry TO mcp_readonly;
GRANT SELECT ON TABLE model_aliases TO mcp_readonly;
GRANT SELECT ON TABLE model_reconcile_runs TO mcp_readonly;
