\connect litellm

ALTER TABLE model_registry
  ADD COLUMN IF NOT EXISTS advertised boolean,
  ADD COLUMN IF NOT EXISTS retired boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS absent_since timestamptz;

UPDATE model_registry
SET advertised = COALESCE(advertised, enabled),
    retired = CASE WHEN status = 'DISABLED' THEN true ELSE COALESCE(retired, false) END
WHERE advertised IS NULL OR status = 'DISABLED';

ALTER TABLE model_registry
  ALTER COLUMN advertised SET DEFAULT true,
  ALTER COLUMN advertised SET NOT NULL;

-- Expand status check to include PENDING, UNHEALTHY, RETIRED (drop/re-add constraint name as used in prod).
ALTER TABLE model_registry DROP CONSTRAINT IF EXISTS model_registry_status_check;
ALTER TABLE model_registry ADD CONSTRAINT model_registry_status_check
  CHECK (status IN (
    'UNKNOWN', 'PENDING', 'HEALTHY', 'UNHEALTHY', 'DEGRADED', 'CRITICAL', 'DISABLED', 'RETIRED'
  ));

CREATE INDEX IF NOT EXISTS model_registry_advertised_idx ON model_registry (advertised);
CREATE INDEX IF NOT EXISTS model_registry_retired_idx ON model_registry (retired);
CREATE INDEX IF NOT EXISTS model_registry_absent_since_idx ON model_registry (absent_since);
