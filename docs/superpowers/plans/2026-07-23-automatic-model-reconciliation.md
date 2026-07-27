# Automatic Model Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically discover and safely reconcile new CLIProxy models on startup, periodically, and after authenticated unknown-model failures.

**Architecture:** A focused `ModelReconciliationService` composes the existing registry discovery/rendering primitives behind a single-flight scheduler. Proxy failures only enqueue trusted-catalog refreshes; they never create client-supplied models directly. Admin status exposes bounded scheduler state.

**Tech Stack:** Python 3.12, FastAPI lifespan tasks, httpx, Pydantic, pytest, existing Postgres model registry.

## Global Constraints

- No synchronous request-path model mutation.
- Transient 429/5xx/timeout failures never remove or disable models.
- Curated registry metadata must survive discovery updates.
- One active reconciliation and at most one pending rerun.
- Default startup delay 30 seconds, interval 900 seconds, expedited minimum interval 60 seconds, timeout 120 seconds.
- Every new or changed endpoint/status field is documented in `docs/openapi/gateway-engine.yaml`.

---

### Task 1: Provider-aware model identity

**Files:**
- Modify: `services/gateway-engine/core/model_registry.py`
- Test: `services/gateway-engine/test_gateway_engine_model_registry.py`

**Interfaces:**
- Produces: `normalize_discovered_model(model_id: str) -> tuple[str, str]`, returning `(registry_id, upstream_id)`.
- Produces: registry aliases that distinguish external alias, canonical registry ID, and exact upstream ID.

- [ ] **Step 1: Write failing table-driven tests** for `gpt-5.6-sol -> (gpt-5-6-sol, gpt-5.6-sol)`, already-dashed GPT names, Claude names, Gemini dotted aliases, the `AI-Gateway:` prefix, empty names, and characters outside the accepted identifier grammar.
- [ ] **Step 2: Run RED:** `cd services/gateway-engine && ../../.venv-ci/bin/python -m pytest test_gateway_engine_model_registry.py -k 'normalize_discovered_model' -v`; expect import/assertion failures because the helper does not exist.
- [ ] **Step 3: Implement the minimal provider-aware normalizer** and route `record_from_cliproxy_model` through it. Preserve exact upstream IDs; do not globally replace dots for non-GPT families.
- [ ] **Step 4: Run GREEN:** repeat the focused pytest command; expect all normalization cases to pass.
- [ ] **Step 5: Commit:** `git add services/gateway-engine/core/model_registry.py services/gateway-engine/test_gateway_engine_model_registry.py && git commit -m "fix(models): normalize discovered client and upstream ids"`.

### Task 2: Single reconciliation operation

**Files:**
- Create: `services/gateway-engine/core/model_reconciliation.py`
- Modify: `services/gateway-engine/api/admin_routes.py`
- Test: `services/gateway-engine/test_gateway_engine_model_reconciliation.py`

**Interfaces:**
- Produces: `ReconciliationTrigger(str, Enum)` with `STARTUP`, `SCHEDULED`, `DEMAND`, `MANUAL`.
- Produces: `ReconciliationResult` containing outcome, phase, counts, verification state, timestamps, and bounded errors.
- Produces: `ModelReconciliationService.run(trigger, requested_model=None) -> ReconciliationResult`.

- [ ] **Step 1: Write failing async tests** using fake discovery/store/render/apply/reload/catalog collaborators. Cover no-change success, discovered-add success, metadata preservation, discovery failure, validation failure, reload rollback, and final catalog verification failure.
- [ ] **Step 2: Run RED:** `cd services/gateway-engine && ../../.venv-ci/bin/python -m pytest test_gateway_engine_model_reconciliation.py -v`; expect module-not-found.
- [ ] **Step 3: Implement the service** with explicit phases: discover, merge, probe additions/stale records, render, validate, atomic apply, reload, verify. Inject collaborators so tests use no filesystem, network, or database.
- [ ] **Step 4: Reuse the service from manual admin sync/reconcile paths** without changing their response schemas; manual dry-run stops before apply.
- [ ] **Step 5: Run GREEN:** focused reconciliation and model-registry tests must pass.
- [ ] **Step 6: Commit:** `git add services/gateway-engine/core/model_reconciliation.py services/gateway-engine/api/admin_routes.py services/gateway-engine/test_gateway_engine_model_reconciliation.py && git commit -m "feat(models): add safe reconciliation service"`.

### Task 3: Scheduler and lifecycle

**Files:**
- Modify: `services/gateway-engine/config.py`
- Modify: `services/gateway-engine/main.py`
- Modify: `.env.example`
- Test: `services/gateway-engine/test_gateway_engine_model_reconciliation.py`

**Interfaces:**
- Produces: `ModelReconciliationService.start()`, `stop()`, and `request(trigger, requested_model=None)`.
- Adds: `GATEWAY_ENGINE_MODEL_RECONCILIATION_ENABLED`, `_STARTUP_DELAY_SEC`, `_INTERVAL_SEC`, `_EXPEDITED_MIN_INTERVAL_SEC`, `_TIMEOUT_SEC`.

- [ ] **Step 1: Write failing tests** proving startup scheduling, periodic runs, cancellation, disabled mode, active-run coalescing, one pending rerun, expedited rate limiting, and timeout reporting.
- [ ] **Step 2: Run RED:** focused scheduler tests must fail because lifecycle methods/config do not exist.
- [ ] **Step 3: Implement scheduler state and async loop** using `asyncio.Lock`, `Event`, and monotonic time. Do not use blocking sleeps outside the cancellable loop.
- [ ] **Step 4: Wire start/stop into `_lifespan`** beside credential sync, cancelling and awaiting the task during shutdown.
- [ ] **Step 5: Document exact defaults in `.env.example`** and run the focused tests GREEN.
- [ ] **Step 6: Commit:** `git add services/gateway-engine/config.py services/gateway-engine/main.py services/gateway-engine/core/model_reconciliation.py services/gateway-engine/test_gateway_engine_model_reconciliation.py .env.example && git commit -m "feat(models): schedule automatic reconciliation"`.

### Task 4: Demand-triggered refresh

**Files:**
- Modify: `services/gateway-engine/api/proxy_routing.py`
- Modify: `services/gateway-engine/api/proxy_router.py`
- Test: `services/gateway-engine/test_gateway_engine.py`
- Test: `services/gateway-engine/test_gateway_engine_model_reconciliation.py`

**Interfaces:**
- Produces: `is_unknown_model_response(response: httpx.Response) -> bool` based on HTTP 400/404 plus typed/bounded provider error fields.
- Consumes: `ModelReconciliationService.request(ReconciliationTrigger.DEMAND, requested_model)`.

- [ ] **Step 1: Write failing tests** for the observed LiteLLM invalid-model body, unrelated 400, 401, 429, 5xx, streaming failures, duplicate triggers, unauthenticated requests, and invalid model names.
- [ ] **Step 2: Run RED:** focused proxy/reconciliation tests must fail because no trigger is emitted.
- [ ] **Step 3: Implement typed unknown-model classification** without unbounded body logging. Trigger only after normal gateway authentication has succeeded and only for a valid normalized name.
- [ ] **Step 4: Enqueue refresh after the upstream response is classified**; return the original response unchanged so the request path never waits for or applies reconciliation.
- [ ] **Step 5: Run GREEN** for focused proxy and reconciliation tests.
- [ ] **Step 6: Commit:** `git add services/gateway-engine/api/proxy_routing.py services/gateway-engine/api/proxy_router.py services/gateway-engine/test_gateway_engine.py services/gateway-engine/test_gateway_engine_model_reconciliation.py && git commit -m "feat(models): refresh catalog after unknown model errors"`.

### Task 5: Status, metrics, and API documentation

**Files:**
- Modify: `services/gateway-engine/api/admin_routes.py`
- Modify: `services/gateway-engine/metrics.py`
- Modify: `services/gateway-engine/test_gateway_engine_admin_api.py`
- Modify: `docs/openapi/gateway-engine.yaml`
- Modify: `docs/API_DOCUMENTATION.md`
- Modify: `docs/ops/RUNBOOK.md`

**Interfaces:**
- Adds: `panels.models.reconciliation` with enabled, interval, active, pending, phase, timestamps, trigger, requested model, counts, verification, and redacted errors.
- Adds bounded metrics for duration, outcome, trigger, and change counts.

- [ ] **Step 1: Write failing admin tests** for idle, running, successful, degraded, disabled, and redacted-error status serialization.
- [ ] **Step 2: Run RED:** focused admin tests must fail because reconciliation status is absent.
- [ ] **Step 3: Add status serialization and bounded metrics**; never label metrics with key aliases, tokens, or unconstrained error text.
- [ ] **Step 4: Update OpenAPI and runbook** with scheduler controls, manual force-run, status interpretation, and rollback steps.
- [ ] **Step 5: Run GREEN:** focused admin tests plus `scripts/ci/check-api-docs.sh` if present; otherwise run the repository's documented OpenAPI validation command.
- [ ] **Step 6: Commit:** stage the listed files and commit `feat(models): expose reconciliation health`.

### Task 6: End-to-end verification

**Files:**
- Modify: `tests/integration/test_gateway_engine_mock.py` or the closest existing mock gateway integration module.

- [ ] **Step 1: Add a mock integration test** where CLIProxy first advertises a new GPT model, reconciliation adds it, LiteLLM reload succeeds, and `/v1/models` then advertises its gateway alias.
- [ ] **Step 2: Add a negative integration test** proving a client-supplied model absent from CLIProxy is never added.
- [ ] **Step 3: Run focused Gate B:** `.venv-ci/bin/python -m pytest tests/integration/ -m mock -v`.
- [ ] **Step 4: Run full fast verification:** `.venv-ci/bin/ruff check services/gateway-engine/`, `.venv-ci/bin/ruff format --check services/gateway-engine/`, gateway-engine unit tests, sync-model probe tests, and mock integration.
- [ ] **Step 5: Commit:** stage the integration test and commit `test(models): verify automatic reconciliation lifecycle`.

