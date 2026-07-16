# K3s Production Quota Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Document the production aggregate quota API and make `quota-summary` query and render that API.

**Architecture:** Gateway Engine remains the sole quota aggregation boundary. The shell helper calls the configured Gateway Engine URL, conditionally adds the admin read header, and delegates JSON formatting to an embedded Python renderer.

**Tech Stack:** OpenAPI 3.0 YAML, Bash, Python 3 standard library.

## Global Constraints

- Production base URL is exactly `https://gateway.infra.plexplease.com`.
- Preserve `GATEWAY_ENGINE_URL`'s existing local default.
- Never print `GATEWAY_ENGINE_ADMIN_KEY`.
- New/discovered endpoints must be documented under `docs/openapi/`.

---

### Task 1: Quota Summary Helper

**Files:**
- Create: `tests/test-quota-summary.sh`
- Modify: `cliproxy-setup.sh`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `GATEWAY_ENGINE_URL`, optional `GATEWAY_ENGINE_ADMIN_KEY`, `GET /admin/quota/status` JSON.
- Produces: `cmd_quota_summary()` human-readable per-account window output and a nonzero exit for HTTP failures.

- [ ] **Step 1: Write failing shell tests** using a fake `curl` executable to capture URL/arguments and return representative account, empty-account, and failure payloads. Assert production URL selection, conditional `x-admin-key`, rendered five-hour/seven-day/binding windows, and failure text.
- [ ] **Step 2: Verify RED** with `bash tests/test-quota-summary.sh`; expect failures because the helper still calls CLIProxy `/auth-files` and renders request counts.
- [ ] **Step 3: Implement minimal helper change** so `cmd_quota_summary` calls `${GATEWAY_ENGINE_URL%/}/admin/quota/status`, conditionally constructs the admin header, and renders `accounts[].quota.windows` without exposing the key.
- [ ] **Step 4: Verify GREEN** with `bash tests/test-quota-summary.sh` and `bash -n cliproxy-setup.sh`; expect all checks and syntax validation to pass.
- [ ] **Step 5: Register the shell regression test** in the `test-scripts` Make target.

### Task 2: Production OpenAPI and Operator Guide

**Files:**
- Modify: `docs/openapi/gateway-engine.yaml`
- Modify: `docs/API_DOCUMENTATION.md`

**Interfaces:**
- Consumes: existing `GET /admin/quota/status` implementation in `services/gateway-engine/api/admin_routes.py`.
- Produces: Scalar-visible endpoint contract and copy-paste production/helper examples.

- [ ] **Step 1: Add OpenAPI assertions** to `tests/test-quota-summary.sh` that parse the YAML and verify the production server, quota path, header parameter, success account/window example, and documented error responses; run and expect RED.
- [ ] **Step 2: Add the production server and full quota operation** to `docs/openapi/gateway-engine.yaml`, matching real fields: `captured_at`, account identity/status, `stale`, quota windows, limits, models, and partial errors.
- [ ] **Step 3: Add operator examples** to `docs/API_DOCUMENTATION.md` for direct production curl, authenticated curl, and `GATEWAY_ENGINE_URL=... ./cliproxy-setup.sh quota-summary`, including the live-refresh timeout note.
- [ ] **Step 4: Verify GREEN** with `bash tests/test-quota-summary.sh` and YAML parsing.

### Task 3: Final Verification and Commit

**Files:**
- Verify all modified files.

**Interfaces:**
- Produces: reviewable branch with test evidence.

- [ ] **Step 1: Run focused verification:** `bash tests/test-quota-summary.sh`, `bash -n cliproxy-setup.sh`, and YAML parsing.
- [ ] **Step 2: Run repository fast checks available without mutating the stable stack:** `make lint`, `make test-scripts`, and relevant unit/mock tests if the environment supports them.
- [ ] **Step 3: Review `git diff --check`, the full diff, and `git status` for scope and secrets.
- [ ] **Step 4: Commit with a Conventional Commit message after all checks pass.
