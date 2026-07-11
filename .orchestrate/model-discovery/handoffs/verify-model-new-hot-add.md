<!-- orchestrate handoff
task: verify-model-new-hot-add
branch: orch/model-discovery/model-new-hot-add
agentId: bc-11a14c89-c361-4dc8-baf1-84bd405d0609
runId: run-43518e60-2e54-4186-b0af-6820e9e49a66
resultStatus: finished
finishedAt: 2026-07-11T09:43:58.260Z
-->

All verification complete. Here is my verdict.

## Verification
unit-test-verified

## Target
`model-new-hot-add` on branch `orch/model-discovery/model-new-hot-add`

## Branch
`orch/model-discovery/model-new-hot-add`

## Execution
- `pip install fastapi httpx pydantic pytest ...` (from Dockerfile pin list; env had no deps) → deps ok
- `python3 -m pytest test_gateway_engine_model_hot_add.py -v` → **4 passed** (requires-admin-key, hot-add upsert+litellm, unreachable partial-success, delete happy path)
- Wrote & ran my own independent repro (`verifier_model_hot_add_repro.py`) against `main.app` via TestClient, inspecting raw JSON (not the author's assertions) → **19/19 checks passed**:
  - Live route table shows `POST /model/new` and `POST /model/delete` registered on `main.app`
  - Path A (no admin key) → HTTP 503, `error.code == admin_key_required`
  - Path B (happy) → HTTP 200, `accepted:true`, `partial_success:false`, registry upserted, `POST http://litellm:4000/model/new` issued with `Authorization: Bearer litellm-master`
  - Path C (litellm raises) → HTTP 200 (no 500), `partial_success:true`, `litellm_add.ok:false`, registry still upserted
  - Path D (`/model/delete` happy) → HTTP 200, registry entry removed, `POST .../model/delete` issued
- `python3 -c "yaml.safe_load(...gateway-engine.yaml)"` → YAML valid; `/model/new` and `/model/delete` present in `paths`
- `grep _require_admin_key api/admin_routes.py` → same helper (`core.admin_shared`) reused by existing `/admin/models` routes; auth path not reinvented
- `gh pr list --head ...` → PR **#369** OPEN, `isDraft:true`, base `main`

## Findings
Per acceptance criterion:
- [x] POST /model/new requires admin key, returns 503 `admin_key_required` without it: Path A observed 503 + code (met)
- [x] Happy path upserts ModelRegistryStore record AND POSTs to `{litellm_url}/model/new` with master key: Path B — fake store contains `gpt-5-4`, fake client call URL + `Bearer litellm-master` asserted (met)
- [x] POST /model/delete implemented symmetrically: Path D — registry removal + `/model/delete` POST observed; handler mirrors `/model/new` incl. registry-unavailable + 404 not-found handling (met)
- [x] LiteLLM-unreachable path returns graceful partial-success (no 500): Path C — HTTP 200, `partial_success:true`, `litellm_add.ok:false`, error `litellm_runtime_add_failed` (met)
- [x] pytest module covers success, missing-admin-key, litellm-unreachable and passes: 4/4 passed (met)
- [x] Endpoint documented under docs/openapi/ and registered per API-doc rule: both paths in `docs/openapi/gateway-engine.yaml` (valid YAML) + note in `docs/API_DOCUMENTATION.md` (met)
- [x] Draft PR against main opened: PR #369 OPEN, draft, base main (met)

Other findings:
- (low) `model_runtime_routes.py` imports `_admin_error` from `api.admin_routes` (returns `code/message/source/redacted`) rather than the leaner `core.admin_shared._admin_error` — harmless, still consistent with existing admin route error shape.
- (low) `except (httpx.HTTPError, Exception)` is redundant (Exception subsumes HTTPError) but functionally correct — catches all unreachable/transport failures as intended.

## Notes & suggestions
- Tests are hermetic (fake httpx client + fake registry store), so no live LiteLLM/Postgres needed — verification is fully reproducible in a bare env after installing the Dockerfile-pinned deps.
- Upstream's own caveats still stand for the planner: Aikido security scan did not complete (MCP auth), and full Gate A/B (`make lint`/`test-unit`/`test-mock`) was not run by the worker. I did not run those either; my scope was the acceptance criteria, all of which are met.
- I committed only a verifier artifact (`services/gateway-engine/verifier_model_hot_add_repro.py`); no target source files were modified. Did not merge/rebase/open PRs.