<!-- orchestrate handoff
task: cheap-drift
branch: orch/model-discovery/cheap-drift
agentId: bc-08b1e7ec-3a69-4358-aa6c-c7ebccbf117d
runId: run-8ffbfeaa-f0a8-4a2f-9982-4e202915ae14
resultStatus: finished
finishedAt: 2026-07-11T09:38:24.110Z
-->

## Status
success

## Branch
`orch/model-discovery/cheap-drift`

## What I did
- Added `scripts/cheap_drift_check.py`:
  - Loads configured aliases from:
    - `litellm-config.yaml` via `model_list[].model_name`
    - optional `config/model-registry.yaml` via `models[].model_id` (also accepts `model_name`/`alias` keys if present)
  - Loads served catalog from either:
    - `GET {CLIPROXY_URL}/v1/models` with `Authorization: Bearer $CLIPROXY_API_KEY`, or
    - `--catalog-file <path>` in OpenAI `/v1/models` JSON shape (`{"data":[{"id":"..."}]}`)
  - Normalizes IDs as documented (`lowercase` + `.` → `-`) before set comparison.
  - Computes and prints JSON report with:
    - `configured_not_served`
    - `served_not_configured`
    - counts, threshold, and source metadata
  - Exits non-zero only when `total_drift_count > --threshold` (default threshold `0`).
  - Contains no completion/probe calls (no `/v1/chat/completions` usage).
- Added `tests/test_cheap_drift_check.py` with required coverage:
  - no-drift => exit 0
  - drift-over-threshold => non-zero exit
  - offline `--catalog-file` parsing (including dot/dash normalization and registry inclusion)
- Added committed offline fixtures under `tests/fixtures/cheap_drift/`:
  - `litellm-config.yaml`
  - `model-registry.yaml`
  - `catalog-no-drift.json`
- Updated `Makefile`:
  - Added `.PHONY` entry for `drift-cheap`
  - Added `drift-cheap` target invoking the checker in offline fixture mode.
- Committed, pushed, and opened draft PR against `main`:
  - PR: https://github.com/echoares-lab/ai-gateway/pull/368

## Measurements
- `python3 -m pytest tests/test_cheap_drift_check.py -q: 2 failed, 1 passed → 3 passed`
- `make drift-cheap total_drift_count: 0 == 0`
- `probe-call pattern matches in scripts/cheap_drift_check.py (chat/completions|max_tokens): 0 == 0`

## Verification
unit-test-verified

## Notes, concerns, deviations, findings, thoughts, feedback
- The PR tool enforces a `cursor/` branch prefix by default; creating the PR from `orch/model-discovery/cheap-drift` required `skip_branch_prefix_check=true` (used because branch name was explicitly mandated).
- `pytest` was not preinstalled in this environment; installed `pytest` via `python3 -m pip install pytest` to run required tests.
- During testing, an empty YAML list edge case (`models:` parsing as null) surfaced; fixed by treating null list keys as empty sets in the checker.
- `.orchestrate/` was not modified or staged.

## Suggested follow-ups
- Run broader repo gate(s) as needed by planner policy (`make lint`, `make test-fast`) before merge.
- If desired, add CI wiring to call `scripts/cheap_drift_check.py --catalog-file ...` as a low-cost scheduled drift signal.