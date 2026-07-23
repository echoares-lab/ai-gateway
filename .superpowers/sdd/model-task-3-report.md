# Model reconciliation Task 3 report

## Outcome

Implemented the production scheduler and FastAPI lifecycle owner for automatic model reconciliation.

## Changes

- Added exact scheduler configuration defaults and `.env.example` documentation: enabled, 30-second startup delay, 900-second interval, 60-second expedited minimum interval, and 120-second run timeout.
- Added cancellable startup/periodic scheduling, disabled mode, demand rate limiting, single active execution, and one coalesced pending rerun.
- Added bounded timeout results and cancellation-safe rollback when a timeout lands after artifact application.
- Added atomic artifact management for `litellm-config.yaml` and `gemini-model-map.json`, preserving prior bytes and file modes and supporting rollback/removal of newly-created files.
- Added bounded authenticated LiteLLM configuration reload.
- Wired a concrete reconciliation factory into FastAPI lifespan startup and shutdown, including trusted discovery, registry reads/writes, probing, rendering, validation, atomic apply, reload, and final catalog verification.
- Preserved non-model LiteLLM configuration sections while replacing rendered model content.

## Verification

- `pytest test_gateway_engine_model_reconciliation.py test_gateway_engine_config.py -q` — 31 passed.
- `ruff check ...` — passed.
- `ruff format --check ...` — passed.
- `make test-fast` — passed: 325 gateway unit tests, 24 probe-classification tests, 4 shell checks, 2 migration tests, and 51 mock integration tests; one pre-existing Starlette deprecation warning.
- `git diff --check` — passed.

## Review fixes

- Replaced the per-container LiteLLM config file mounts in both Compose stacks
  with a named reconciliation-artifact volume. A one-shot initializer seeds the
  committed baseline only when the shared config is absent; gateway-engine
  writes `/config/litellm-config.yaml` and LiteLLM consumes that exact path.
- Deferred changed-model registry persistence until artifact apply, LiteLLM
  reload, and final catalog verification succeed. Persistence failures after
  activation now roll artifacts back, and failed reloads leave the registry
  unchanged so the next run rediscovers and retries the model.
- Made LiteLLM reload fail closed before issuing an HTTP request when the master
  key is empty or whitespace-only.

### TDD evidence

- The Compose contract test first failed because neither Compose file declared
  `litellm_reconciliation_artifacts`.
- The reload-auth regression first observed one client request with an empty
  master key.
- The retry regression first observed the new model already persisted after a
  failed reload, preventing a subsequent run from treating it as an addition.

### Review-fix verification

- Focused new regressions — 4 passed.
- Reconciliation, model-registry, and Compose suites — 80 passed.
- Both `docker compose ... config` validations — passed.
- `make test-fast` — passed: lint and format, 327 gateway unit tests, policy and
  drift validation, 24 probe-classification tests, 4 shell probe checks, 4
  Compose migration/contract tests, and 51 mock integration tests.
- The pinned LiteLLM initializer image contains `/bin/sh`, `cp`, and `chmod`.
