<!-- orchestrate handoff
task: model-new-hot-add
branch: orch/model-discovery/model-new-hot-add
agentId: bc-e4451116-6d40-4c5e-8e00-32c31164a5c0
runId: run-7ecaac5d-bfa6-4f7e-823c-a04fa9e5f70b
resultStatus: finished
finishedAt: 2026-07-11T09:41:10.312Z
-->

## Status
success

## Branch
`orch/model-discovery/model-new-hot-add`

## What I did
- Implemented hot runtime model mutation endpoints in `services/gateway-engine/api/model_runtime_routes.py`:
  - `POST /model/new`
  - `POST /model/delete`
- Reused the existing admin auth path by calling `_require_admin_key` exactly (same unauthenticated 503 `admin_key_required` response shape).
- Implemented `/model/new` behavior to:
  - upsert via `ModelRegistryStore` using `ModelRegistryWriteRequest.to_record()`
  - POST to `{LITELLM_URL}/model/new` with `Authorization: Bearer $LITELLM_MASTER_KEY`
  - return structured payload including registry record + `litellm_add` outcome
  - degrade gracefully to partial success when LiteLLM is unreachable (no 500 crash).
- Implemented symmetric `/model/delete` behavior to:
  - remove model from registry (`hard_delete_model`)
  - POST to `{LITELLM_URL}/model/delete` with master-key bearer
  - return structured payload with `litellm_delete` outcome and partial-success handling.
- Added runtime mutation response/request models in `services/gateway-engine/core/model_registry.py`:
  - `LiteLLMRuntimeMutationResult`
  - `ModelRuntimeMutationResponse`
  - `ModelHotAddResponse`
  - `ModelDeleteRequest`
  - `ModelHotDeleteResponse`
- Registered the new router in `services/gateway-engine/main.py` alongside existing admin routers.
- Added targeted tests in `services/gateway-engine/test_gateway_engine_model_hot_add.py` covering:
  - happy path (registry upsert + LiteLLM `/model/new` call assertion)
  - missing admin key (503 + `admin_key_required`)
  - LiteLLM-unreachable partial-success behavior (no crash)
  - symmetric `/model/delete` happy path.
- Documented endpoints in `docs/openapi/gateway-engine.yaml` and added registration note in `docs/API_DOCUMENTATION.md`.
- Committed, pushed, and opened a draft PR against `main`.

## Measurements
- `python3 -m pytest services/gateway-engine/test_gateway_engine_model_hot_add.py -q: 0 passing → 4 passing`
- `runtime hot-mutation endpoints in gateway OpenAPI spec: 0 → 2`
- `runtime hot-mutation route handlers implemented: 0 → 2`

## Verification
unit-test-verified

## Notes, concerns, deviations, findings, thoughts, feedback
- Draft PR opened against `main` (head: `orch/model-discovery/model-new-hot-add`): `#369`.
- Aikido MCP scan could not complete due auth/token failure despite login status reporting signed-in.  
  The Aikido MCP server is required for security scanning but is not available reliably in this run. Run `/aikido:setup` to configure/refresh it, then re-run `aikido_full_scan`.
- No UI changes were made; screen recording requirement is not applicable.

## Suggested follow-ups
- Run full Gate A/B suite for this branch (`make lint`, `make test-unit`, `make test-mock`) before merge.
- Re-run Aikido scan after MCP auth refresh to close the security-scan requirement cleanly.