# Model Task 1 Report

Status: DONE_WITH_CONCERNS

## Implementation

- Added `normalize_discovered_model(model_id) -> (registry_id, upstream_id)` with identifier validation.
- Removed the external `AI-Gateway:` prefix while preserving the exact remaining upstream identifier.
- Normalized dots only for OpenAI-family discovered identifiers; Claude and Gemini dotted identifiers remain unchanged.
- Routed `record_from_cliproxy_model` through the new helper and recorded external, registry, and upstream identity aliases separately.
- Updated the older CLIProxy sync assertions to reflect provider-aware Claude identity.

## TDD Evidence

- RED prescribed command: unavailable because `../../.venv-ci/bin/python` does not exist in this worktree/environment (exit 127).
- RED fallback: `python3 -m pytest test_gateway_engine_model_registry.py -k 'normalize_discovered_model' -v` failed during collection with the expected missing `normalize_discovered_model` import.
- GREEN focused: the same fallback command passed 11 tests (27 deselected).
- Registry module: `python3 -m pytest test_gateway_engine_model_registry.py -v` passed 38 tests.
- Gateway unit suite: `python3 -m pytest test_gateway_engine*.py -q` passed 289 tests with one pre-existing Starlette deprecation warning.
- Lint: `python3 -m ruff check services/gateway-engine/core/model_registry.py services/gateway-engine/test_gateway_engine_model_registry.py` passed.
- Diff hygiene: `git diff --check` passed.

## Self-review

- Only the two task-scoped source/test files are included in the commit.
- Exact upstream IDs feed both `upstream_model` and `litellm_model`.
- The accepted identifier grammar is constrained to an alphanumeric first character followed by alphanumerics, dot, underscore, or dash.
- Invalid or empty identifiers raise `ValueError`; missing CLIProxy `id`/`model` entries retain the existing `None` behavior.

## Concern

The brief's exact `.venv-ci` interpreter path was absent, so verification used the system Python 3 environment, which contains the repository test dependencies. The full gateway unit suite passed there.

## Fix Review

Status: FIXED

- Added regression tests proving discovered aliases survive merges into existing records and are written by `ModelRegistryStore.upsert_models` in the model transaction.
- Added deterministic alias deduplication for the schema's global `model_aliases.alias` primary key. For generated identity aliases, precedence is `upstream` over `external` over `registry`; pre-existing custom kinds such as `client` and `compat` take precedence over generated identities with the same text.
- Alias persistence uses `ON CONFLICT (alias) DO UPDATE` so a single schema-level alias row is updated atomically with its model identity and metadata.
- RED: `python3 -m pytest test_gateway_engine_model_registry.py -k 'semantic_precedence or keeps_existing_aliases or persists_deduplicated_aliases' -v` collected 42 tests, selected 4, and failed all 4 before the implementation (the store assertion initially also exposed a test-only `pytest.ANY` typo, corrected to `unittest.mock.ANY` before GREEN).
- GREEN focused: the same command passed 4 tests, with 38 deselected and one pre-existing Starlette deprecation warning.
- Full registry verification: `python3 -m pytest test_gateway_engine_model_registry.py -v` passed 42 tests in 0.49s, with one pre-existing Starlette deprecation warning.
- The prescribed `.venv-ci` interpreter remains unavailable; verification used system Python 3 as in the original task report.
