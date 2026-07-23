-- Expand model_registry.status to values already emitted by reconciliation probes.
ALTER TABLE model_registry
    DROP CONSTRAINT IF EXISTS model_registry_status_check;

ALTER TABLE model_registry
    ADD CONSTRAINT model_registry_status_check
    CHECK (status IN (
        'UNKNOWN', 'HEALTHY', 'DEGRADED', 'CRITICAL', 'DISABLED',
        'PENDING', 'UNHEALTHY'
    ));
