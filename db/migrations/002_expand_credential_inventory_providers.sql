\connect litellm

-- Align credential_inventory.provider CHECK with init-db.sql (OAuth CLIProxy providers).
ALTER TABLE credential_inventory DROP CONSTRAINT IF EXISTS credential_inventory_provider_check;
ALTER TABLE credential_inventory ADD CONSTRAINT credential_inventory_provider_check
    CHECK (provider IN (
        'openai', 'anthropic', 'gemini', 'xai', 'moonshot',
        'antigravity', 'gemini-cli', 'codex', 'claude'
    ));
