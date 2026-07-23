# Model Task 2 Report

## Status

Implemented the single automatic model reconciliation operation and reused it from the existing manual model sync and reconcile endpoints without changing their response models.

## Scope

- Added `ReconciliationTrigger`, `ReconciliationResult`, and the injected `ModelReconciliationService.run(...)` pipeline.
- Implemented discover, merge, additions/stale probing, render, validate, persistence, atomic apply, reload, catalog verification, and artifact rollback phases.
- Preserved curated metadata through the existing `merge_discovered_model` behavior.
- Added bounded structured errors, timestamps, counts, and verification state.
- Kept scheduling, lifecycle/coalescing, and demand-trigger wiring out of Task 2.
- Added seven async fake-collaborator tests covering every scenario named in the task brief.

## TDD Evidence

- RED: `python3 -m pytest test_gateway_engine_model_reconciliation.py -v` failed during collection with `ModuleNotFoundError: No module named 'core.model_reconciliation'`.
- GREEN focused: `python3 -m pytest test_gateway_engine_model_reconciliation.py test_gateway_engine_model_registry.py -q` passed 50 tests.
- GREEN relevant suite: `python3 -m pytest test_gateway_engine*.py -q` passed 301 tests with one pre-existing Starlette/httpx deprecation warning.
- Lint/format: Ruff check and format check passed for all three touched implementation/test files.

## Commit

`2aa15db` (`feat(models): add safe reconciliation service`)

## Concerns

- The brief's `../../.venv-ci/bin/python` interpreter does not exist in this worktree or the related main checkout. Verification used the available system `python3` (Python 3.14.4) with the repository's pytest and Ruff dependencies.
- Concrete production atomic file replacement/reload collaborators remain intentionally outside this operation and must be supplied when Task 3 wires the service lifecycle.

## Review Fixes

- New discoveries are converted to `PENDING`/disabled before their required probe and become enabled only when the probe reports `healthy`; unhealthy additions remain persisted but are excluded from rendered resources.
- Same-key discovery metadata no longer replaces curated metadata with null or blank string values.
- Persistence now has an explicit `persist` phase, so upsert failures report `persist_failed` instead of `validate_failed`.
- Reconciliation exposes the collaborator's actual persisted count, and non-dry-run admin sync uses it for `imported_count`; dry-run import-count semantics remain unchanged.

### Review TDD Evidence

- RED focused: four new regressions failed for unsafe unhealthy additions, `owned_by=None` metadata replacement, incorrect upsert failure phase, and inferred admin import counts.
- GREEN focused: `pytest -q services/gateway-engine/test_gateway_engine_model_reconciliation.py services/gateway-engine/test_gateway_engine_model_registry.py -k 'unhealthy_discovered_add or preserves_curated_metadata_when or upsert_failure_is_reported or reports_actual_upsert_count'` — 4 passed, 50 deselected.
- GREEN relevant suite: `pytest -q services/gateway-engine/test_gateway_engine_model_reconciliation.py services/gateway-engine/test_gateway_engine_model_registry.py services/gateway-engine/test_gateway_engine_admin_api.py services/gateway-engine/test_gateway_engine_admin_policy_trace.py services/gateway-engine/test_gateway_engine_admin_policy_integration.py` — 73 passed with one pre-existing Starlette/httpx deprecation warning.

## Curated Metadata Ownership Follow-up

- Corrected same-key metadata ownership: discovery now contributes only non-empty keys absent from the existing curated `policy_metadata`; it cannot replace an existing curated value with a different non-empty discovery value.
- RED: `pytest -q services/gateway-engine/test_gateway_engine_model_registry.py -k preserves_existing_curated_policy_metadata` failed because discovery replaced `owned_by="curated-owner"` with `owned_by="generic-discovery-owner"`.
- GREEN focused: `pytest -q services/gateway-engine/test_gateway_engine_model_registry.py -k 'merge_discovered_model'` — 2 passed, 43 deselected, with one pre-existing Starlette/httpx deprecation warning.
- GREEN covering suite: `pytest -q services/gateway-engine/test_gateway_engine_model_reconciliation.py services/gateway-engine/test_gateway_engine_model_registry.py services/gateway-engine/test_gateway_engine_admin_api.py services/gateway-engine/test_gateway_engine_admin_policy_trace.py services/gateway-engine/test_gateway_engine_admin_policy_integration.py` — 74 passed with one pre-existing Starlette/httpx deprecation warning.
- Lint/format: `ruff check services/gateway-engine/core/model_registry.py services/gateway-engine/test_gateway_engine_model_registry.py` and `ruff format --check services/gateway-engine/core/model_registry.py services/gateway-engine/test_gateway_engine_model_registry.py` passed.
