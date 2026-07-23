# OpenBao Stable Key Escrow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve launcher key identity by escrowing gateway-generated virtual-key secrets in OpenBao and recovering the same token by alias.

**Architecture:** A narrow secret-store client and key service sit behind gateway admin endpoints. Creation uses write-ahead pending escrow, exact-token LiteLLM creation, verification, then activation. Recovery and legacy import never delete or rotate keys.

**Tech Stack:** Python 3.12, FastAPI/httpx, OpenBao KV v2 HTTP API, LiteLLM admin API, pytest.

## Global Constraints

- Runtime OpenBao policy has no delete/destroy permission.
- Never rotate or delete an existing key automatically.
- Never log, metric-label, URL-encode, or echo a token.
- Secret responses use `Cache-Control: no-store`.
- OpenBao endpoint changes must be documented in `docs/openapi/gateway-engine.yaml`.

---

### Task 1: OpenBao client and configuration

**Files:**
- Create: `services/gateway-engine/core/launcher_key_escrow.py`
- Modify: `services/gateway-engine/config.py`
- Modify: `.env.example`
- Create: `services/gateway-engine/test_gateway_engine_launcher_key_escrow.py`

**Interfaces:**
- Produces: `EscrowRecord(alias, token, team_id, litellm_key_id, state, schema_version, created_at)`.
- Produces: `OpenBaoEscrowClient.read(alias)`, `write_pending(record)`, and `activate(alias, litellm_key_id)`.
- Adds OpenBao address/auth/KV mount/prefix/timeout settings.

- [ ] **Step 1: Write failing tests** with `httpx.MockTransport` for KV-v2 read/write, missing record, CAS conflict, auth failure, timeout, redacted exceptions, and hashed path derivation.
- [ ] **Step 2: Run RED:** focused escrow tests must fail because the module does not exist.
- [ ] **Step 3: Implement minimal client** with injected `httpx.AsyncClient`; authenticate through a workload token supplier so Kubernetes auth/AppRole token renewal is replaceable without changing escrow logic.
- [ ] **Step 4: Add configuration validation** that disables creation/recovery with a typed `secret_store_unavailable` result when required settings are absent.
- [ ] **Step 5: Run GREEN and commit** as `feat(keys): add OpenBao escrow client`.

### Task 2: Stable-key service transaction

**Files:**
- Create: `services/gateway-engine/core/launcher_key_service.py`
- Modify: `services/gateway-engine/admin_api.py`
- Test: `services/gateway-engine/test_gateway_engine_launcher_key_escrow.py`

**Interfaces:**
- Produces: `create_key(request)`, `recover_key(alias)`, and `import_key(alias, token)` service methods.
- Produces stable codes: `key_alias_not_found`, `key_secret_not_escrowed`, `key_identity_mismatch`, `secret_store_unavailable`, `key_creation_incomplete`.

- [ ] **Step 1: Write failing transaction tests** covering successful write-ahead creation, OpenBao failure before LiteLLM, LiteLLM failure after pending escrow, retry/resume with the same token, verification failure, existing alias, recovery, and legacy import.
- [ ] **Step 2: Run RED:** tests must fail because the service does not exist.
- [ ] **Step 3: Implement gateway token generation** with the OS CSPRNG and LiteLLM's accepted virtual-key format; pass the exact token to LiteLLM `/key/generate`.
- [ ] **Step 4: Implement pending/active state transitions and idempotent resume**. Never delete or generate a second token for an existing/pending alias.
- [ ] **Step 5: Implement legacy import verification** by authenticating the supplied token against LiteLLM key-info before escrow; refuse overwrite when a different active secret exists.
- [ ] **Step 6: Run GREEN and commit** as `feat(keys): preserve stable launcher key secrets`.

### Task 3: Protected admin contracts

**Files:**
- Modify: `services/gateway-engine/admin_api.py`
- Modify: `services/gateway-engine/test_gateway_engine_admin_api.py`
- Modify: `docs/openapi/gateway-engine.yaml`
- Modify: `docs/API_DOCUMENTATION.md`

**Interfaces:**
- Adds: `GET /admin/keys/{alias}/secret`.
- Adds: `POST /admin/keys/{alias}/import`.
- Changes: `POST /admin/keys` to call stable-key service.

- [ ] **Step 1: Write failing endpoint tests** for admin authentication, path alias validation, no-store headers, typed status mappings, response redaction, creation, recovery, and import.
- [ ] **Step 2: Run RED:** focused admin tests must fail on missing routes/behavior.
- [ ] **Step 3: Implement Pydantic request/response types and endpoints**. Token fields may be present only in successful JSON bodies and must never be interpolated into exceptions.
- [ ] **Step 4: Document schemas, status codes, and mixed-version behavior** in OpenAPI and API documentation.
- [ ] **Step 5: Run GREEN and commit** as `feat(admin): expose stable key recovery contracts`.

### Task 4: OpenBao policy and k3s deployment contract

**Files:**
- Modify: `docs/CICD_PHASE2_CD_K3S.md`
- Modify: `docs/CICD_PHASE2_STAGING.md`
- Modify: `docs/ops/RUNBOOK.md`
- Modify: the authoritative `echoares-lab/k3s-01` manifests in a separate claimed issue/worktree.

- [ ] **Step 1: Document exact KV path and least-privilege policy** granting create/read/update/list metadata but excluding delete/destroy.
- [ ] **Step 2: Add workload auth and environment references** to staging first; do not mount a root or general admin token.
- [ ] **Step 3: Add a policy verification command** that proves allowed read/write and denied delete against a disposable test path.
- [ ] **Step 4: Document legacy import, incomplete-creation repair, token redaction, and rollback procedures.**
- [ ] **Step 5: Validate manifests/docs and commit** as `docs(keys): define OpenBao escrow operations`; the k3s change remains its own reviewed PR.

### Task 5: Security and integration verification

**Files:**
- Modify: `tests/integration/test_gateway_engine_mock.py` or nearest admin mock integration module.

- [ ] **Step 1: Add integration coverage** for create → local loss simulation → recover same token, plus pre-escrow import → recover.
- [ ] **Step 2: Add failure-path coverage** proving no second LiteLLM creation and no OpenBao delete on every recoverable error.
- [ ] **Step 3: Run focused tests**, ruff, mock integration, API validation, and the repository secret scanner.
- [ ] **Step 4: Inspect captured logs** and assert neither test token nor Authorization header appears.
- [ ] **Step 5: Commit** as `test(keys): verify stable escrow recovery`.
