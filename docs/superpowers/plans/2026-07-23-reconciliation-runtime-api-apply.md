# Reconciliation Runtime API Apply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make automatic model reconciliation work on k3s by applying catalog changes through LiteLLM's runtime API (`/model/new`, `/model/delete`) instead of rewriting the read-only ConfigMap-mounted `litellm-config.yaml`.

**Architecture:** Keep discover → merge → probe → render → validate → apply → reload → verify → persist. Replace the litellm file write inside `apply` with additive runtime mutations for enabled changed models (and deletes for disabled ones). Continue writing `gemini-model-map.json` via the existing atomic file manager (image-local path). Wire `DATABASE_URL` on gateway-engine in k3s so the Postgres registry is available.

**Tech Stack:** Python 3.12, httpx, FastAPI gateway-engine, LiteLLM runtime API (`store_model_in_db: true`), k3s-01 Deployment env.

---

## File map

| File | Responsibility |
|------|----------------|
| `services/gateway-engine/core/model_reconciliation.py` | `LiteLLMRuntimeApplyManager` + service apply signature |
| `services/gateway-engine/api/model_runtime_routes.py` | Reuse shared payload helper |
| `services/gateway-engine/main.py` | Wire hybrid apply (runtime + gemini file) |
| `services/gateway-engine/test_gateway_engine_model_reconciliation.py` | Unit tests for runtime apply/rollback |
| `k3s-01` gateway-engine Deployments | `DATABASE_URL` from `litellm_db_url` |

---

### Task 1: Runtime apply manager (TDD)

**Files:**
- Modify: `services/gateway-engine/core/model_reconciliation.py`
- Test: `services/gateway-engine/test_gateway_engine_model_reconciliation.py`

- [ ] **Step 1: RED** — tests that enabled changed models call `/model/new`, disabled call `/model/delete`, partial failure rolls back, duplicate-add is treated as success
- [ ] **Step 2: GREEN** — implement `LiteLLMRuntimeApplyManager`
- [ ] **Step 3: Wire** — change `ModelReconciliationService` apply call to pass `(resources, models, changed_ids)`; update fakes
- [ ] **Step 4: Wire main.py** — hybrid apply (gemini file + runtime litellm); reload stays
- [ ] **Step 5: Run** focused reconciliation + hot-add tests

### Task 2: k3s DATABASE_URL

**Files:**
- `overlays/k3s-01/gateway-engine/gateway-engine.yaml`
- `overlays/staging/core-workloads.yaml` (gateway-engine env)

- [ ] **Step 1:** Add `DATABASE_URL` secretKeyRef `litellm_db_url`
- [ ] **Step 2:** PR + merge; confirm live `registry_available: true` without manual patch

### Task 3: Verify production reconciliation

- [ ] Force manual reconcile or wait for startup
- [ ] Expect `outcome=success` and non-zero `model_registry` rows
- [ ] Confirm new models appear on LiteLLM `/v1/models`
