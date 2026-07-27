# Model reconciliation whole-branch review fixes

- Production additions are probed through trusted CLIProxy using the exact
  `upstream_model` before their LiteLLM alias is applied.
- Failed, missing, rate-limited, timeout, and transient additions remain disabled
  and retryable; a later successful probe enables and advertises them.
- Successful probe results expire after the configurable
  `GATEWAY_ENGINE_MODEL_RECONCILIATION_PROBE_STALE_SEC` interval (default 300).
- Existing enabled models remain enabled during transient probe failures.
- Mutating `POST /admin/models/sync` now enqueues the lifespan-owned singleton
  scheduler; dry-run remains isolated and read-only.
- Tests cover the original absent-alias incident through the concrete production
  factory, retry recovery, staleness, preservation, and scheduler enqueueing.

Verification: `make test-fast` passed (373 gateway tests, 24 probe-classifier
tests, 4 migration tests, 4 shell probe checks, and 53 mock integration tests).

## Final persistence and retry review

- A disabled-to-enabled retry is now an effective change even when discovery has
  no add/update diff, so the second run applies artifacts, reloads LiteLLM, and
  verifies the newly advertised alias.
- PostgreSQL upsert now inserts and conflict-updates `status`, `probe_status`,
  `probe_http_status`, and `probe_checked_at` in the same transaction.
- Pending legacy null, preserve/401/403, transient, timeout, missing, and
  rate-limited states remain retryable; enabled existing models remain preserved.
- Source-specific manual sync retains `litellm-config` or `cliproxy` response
  semantics and real imported/skipped counts while executing under the singleton
  scheduler operation lock.

Final verification: `make test-fast` passed (379 gateway tests, 24
probe-classifier tests, 4 migration tests, 4 shell probe checks, and 53 mock
integration tests).
