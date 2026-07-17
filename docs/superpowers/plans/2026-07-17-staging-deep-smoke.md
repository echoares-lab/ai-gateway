# Staging Deep Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `scripts/ops/deep-smoke.sh` (+ helper) as the staging `--full` promote gate, with offline tests and CICD/TESTING doc wire-in — without replacing thin Gate D.

**Architecture:** Shell entrypoint for operators; small Python helper for JSON/SSE/DB assertions; kubectl/psql for SpendLogs; soft admin quota check while schema is in flux.

**Tech Stack:** bash, python3 (stdlib), curl, kubectl, psql (via kubectl exec), pytest or shell fakes for offline tests.

## Global Constraints

- Work only in `/home/dev/worktrees/ai-gateway-<issue>/` — never edit stable `:4000` checkout for feature work.
- One GitHub atomic issue = one claim = one branch = one worktree = one PR.
- Soft quota: assert `GET /admin/quota/status` → 2xx + JSON object only; do **not** freeze field contracts until a follow-up issue after OpenAPI freeze.
- Default `--env staging`; prod is optional/incident.
- No secrets in git; document `DEEP_SMOKE_*` in `.env.example` only.
- Do not expand `post-merge-gate-d.yml` in this epic unless a child issue explicitly says so.
- Spec: `docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md`.

## File map

| File | Responsibility |
|------|----------------|
| `scripts/ops/deep-smoke.sh` | CLI flags, env defaults, orchestration, markdown summary, exit codes |
| `scripts/ops/deep_smoke.py` | Parse responses, SSE checks, SpendLogs match helper, soft quota check |
| `tests/test_deep_smoke.py` (or `tests/test-deep-smoke.sh`) | Offline fakes: args, soft quota, spend match, exit taxonomy |
| `.env.example` | `DEEP_SMOKE_*` placeholders |
| `docs/CICD_PHASE2_STAGING.md` | Promote-gate checklist step |
| `docs/CICD_PHASE2_CD_K3S.md` | Staging deep smoke vs thin prod Gate D |
| `docs/TESTING.md` + appendix | Gate matrix row for deep smoke |
| `docs/ROADMAP.md` | Epic approval under Next (coordination PR) |

---

### Task 0: Roadmap + epic scaffolding (docs-only coordination)

**Issue:** epic parent + this docs PR  
**Files:** `docs/ROADMAP.md`, design + this plan (already drafted)

- [ ] Add Next section for Staging Deep Smoke epic with ordered children
- [ ] Ensure design + plan are on the branch
- [ ] Open PR; do not implement script in this task if split

---

### Task 1: Scaffold `--quick` mode + offline tests

**Depends on:** Task 0 merged or stacked on its branch if explicitly allowed  
**Files:** `scripts/ops/deep-smoke.sh`, `scripts/ops/deep_smoke.py`, `tests/test_deep_smoke.py`, `.env.example`

- [ ] Write failing offline tests for `--help`, `--env` defaults, `--quick` check list order
- [ ] Implement entrypoint: health, ready, version, models, one completion, pods Ready
- [ ] Fake curl/kubectl in tests; no live network required for Gate A
- [ ] `bash -n scripts/ops/deep-smoke.sh` + offline tests green
- [ ] Commit: `feat(ops): add deep-smoke --quick scaffold`

---

### Task 2: `--full` HTTP API shapes, streaming, provider families

**Depends on:** Task 1  
**Files:** `scripts/ops/deep-smoke.sh`, `scripts/ops/deep_smoke.py`, tests

- [ ] Failing tests for responses/messages shape helpers and SSE chunk detection
- [ ] Implement chat / responses / messages / stream / claude+gpt+gemini allowlist
- [ ] Tag `end_user=deep-smoke-<ts>` on all requests
- [ ] Offline tests green; commit: `feat(ops): deep-smoke full HTTP API checks`

---

### Task 3: Admin soft checks (quota soft)

**Depends on:** Task 1 (can parallel Task 2 if no file conflict — prefer stack after 2 if same files)  
**Files:** helper + tests + short note in `docs/API_DOCUMENTATION.md`

- [ ] Test: soft quota passes on any JSON object 2xx; fails on 5xx/non-JSON
- [ ] Implement `/admin/status`, credentials list, soft `/admin/quota/status`
- [ ] Document soft contract + link to quota OpenAPI follow-up
- [ ] Commit: `feat(ops): deep-smoke soft admin and quota checks`

---

### Task 4: Cluster Jobs + SpendLogs DB verification

**Depends on:** Task 2 (needs tagged completion / request id)  
**Files:** helper + tests + script

- [ ] Test SpendLogs matcher against fixture rows (`end_user` / `request_id`)
- [ ] Implement kubectl pod/Job checks + psql/kubectl exec poll loop
- [ ] Clear error if kube/DB unavailable on staging `--full`
- [ ] Commit: `feat(ops): deep-smoke SpendLogs and cluster checks`

---

### Task 5: Promotion docs + Langfuse warn-only + summary format

**Depends on:** Tasks 1–4 (or docs-only portions can start after Task 1)  
**Files:** `docs/CICD_PHASE2_STAGING.md`, `docs/CICD_PHASE2_CD_K3S.md`, `docs/TESTING.md`, appendix

- [ ] Add promote checklist: run staging `--full` before digest pin
- [ ] Clarify Gate D remains thin on prod
- [ ] Langfuse optional warn; `--strict` fails
- [ ] Commit: `docs(ops): wire deep-smoke into staging promote gate`

---

### Task 6 (follow-up, blocked): Harden quota asserts

**Depends on:** Quota OpenAPI schema frozen + operator signoff  
**Status:** `status:blocked` until freeze

- [ ] Replace soft quota check with schema-validated asserts
- [ ] Update OpenAPI examples and deep-smoke tests together

---

## Live verification (operator, not CI)

Staging (required for promote):

```bash
./scripts/ops/deep-smoke.sh --env staging --full
```

Prod (optional incident):

```bash
./scripts/ops/deep-smoke.sh --env prod --quick
```

## Parallelism notes for subagents

| Can parallelize | Serialize |
|-----------------|-----------|
| Task 5 docs after Task 1 lands API surface names | Tasks 1→2→4 (same scripts) |
| Task 3 after Task 1 if careful merge | Task 6 until quota freeze |
| Epic/ROADMAP PR vs script PRs once epic exists | Hotspot: `scripts/ops/deep-smoke.*` — one agent at a time |
