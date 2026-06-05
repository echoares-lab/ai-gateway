---
work_type: type:coordination
summary: Phase 0 prerequisites that must land before Epic #38 Policy Engine Phase 1 implementation.
problem: |
  Epic #38 (Policy Engine for routing & credential governance) depends on signals,
  tenancy, adaptive routing, and credential inventory control loops that are partially
  implemented or still in flight. Starting policy-engine service integration before
  these foundations land would produce stubbed state sources and premature contracts.
why_now: |
  docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md and docs/ROADMAP.md now formalize Epic #38
  as planned-but-blocked. This issue tracks the explicit gate checklist.
scope: |
  Track completion status of Phase 0 items. No implementation in this issue — child
  issues remain the execution unit per REPO_IMPROVEMENT_WORKFLOW.md.
non_goals:
  - Implementing policy-engine service (Epic #38 Phase 1)
  - Modifying litellm-config.yaml fallbacks for policy overrides
acceptance:
  - [ ] All Phase 0 items below marked done or explicitly waived with ADR note
  - [ ] Epic #38 Phase 1 child issues (38-2..38-4) remain unclaimed until gate clears
  - [ ] ROADMAP.md "Planned — blocked on Phase 0" section references this file
dependencies:
  - docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md
parent_epic: "#38 Policy engine for routing & credential governance"
github_issue: #119
---

# Policy Engine — Phase 0 Prerequisites

Epic #38 **must not** enter Phase 1 implementation until every row in this table is
**Done** or **Waived** (with documented rationale). Schema design (38-1) and pool
migration design (38-10) may proceed in parallel.

Design reference: [docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md](../docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md)

## Gate checklist

| ID | Prerequisite | Parent epic | Status | Blocks |
|----|--------------|-------------|--------|--------|
| P0-1 | Tenancy metadata in translator (`ak-*` → metadata) | [#30](https://github.com/echoares-lab/ai-gateway/issues/30) | **Done** ([#79](https://github.com/echoares-lab/ai-gateway/pull/79)) | 38-4, 38-5 |
| P0-2 | Passive per-provider health/latency/error/429 signals | [#59](https://github.com/echoares-lab/ai-gateway/issues/59) / [#31](https://github.com/echoares-lab/ai-gateway/issues/31) | **Done** ([#63](https://github.com/echoares-lab/ai-gateway/pull/63)) | 38-7, 38-8 |
| P0-3 | Adaptive fallback ordering (latency + cooldown scoring) | [#60](https://github.com/echoares-lab/ai-gateway/issues/60) / [#31](https://github.com/echoares-lab/ai-gateway/issues/31) | **Done** ([#64](https://github.com/echoares-lab/ai-gateway/pull/64)) | 38-8 |
| P0-4 | LiteLLM team RPM/TPM/dollar budget enforcement scoped | TENANCY-3 / [#30](https://github.com/echoares-lab/ai-gateway/issues/30) | **Done** ([policy-engine-p0-4-budget.md](./policy-engine-p0-4-budget.md)) | 38-9 |
| P0-5 | `credential_inventory` table + prober sync | [#33](https://github.com/echoares-lab/ai-gateway/issues/33) | **Partial** (read-only sync live) | 38-7, 38-10 |
| P0-6 | Credential inventory → active rotation (degraded creds excluded from routing) | [#33](https://github.com/echoares-lab/ai-gateway/issues/33) | **Done** | 38-12, 38-13 |
| P0-7 | Config promotion validation path for policy profiles | [#35](https://github.com/echoares-lab/ai-gateway/issues/35) | **Done** ([policy-engine-p0-7-promotion.md](./policy-engine-p0-7-promotion.md)) | 38-5 promotion |

## What can start before gate clears

| Work item | Issue | Notes |
|-----------|-------|-------|
| RoutingContext / RoutingDecision schemas | 38-1 | **Done** — quota-aware fields (`QuotaHeadroom`, `quota_aware_mode`, `deprioritized_credentials`); see [38-01](./policy-engine-38-01-schemas.md) |
| Pool schema migration design | 38-10 | **Done** — `affinity_mode` includes `quota-aware`; see [38-10](./policy-engine-38-10-credential-pool-schema.md) |
| Policy-engine stub scaffold | 38-2 | **Done** — `services/policy-engine/main.py`; see [38-02](./policy-engine-38-02-scaffold.md) |
| Agent dispatch index | — | [policy-engine-dispatch.md](./policy-engine-dispatch.md) |
| Design document | — | `docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md` |
| Policy-engine stub service | 38-2 | Scaffold only; do not wire translator until P0-1..P0-3 minimum |

## Minimum gate for translator integration (38-4)

At least **P0-1**, **P0-2**, and **P0-3** must be **Done** before enabling
`POLICY_ENGINE_ENABLED=true` in any shared environment. Budget (P0-4) and credential
rotation (P0-6) are required before production enforcement of gates 38-9 and 38-12.

**Status (2026-06-05):** P0-1..P0-3 are **Done**. Translator policy-engine wiring
(38-4) may proceed in dev; full Epic #38 Phase 1 remains blocked on P0-4..P0-7.

## Verification commands (when prerequisites land)

```bash
# P0-2: provider signals present in translator metrics
curl -s http://localhost:4000/metrics | grep translator_provider

# P0-3: adaptive routing config active
grep -A5 'routing_strategy' litellm-config.yaml

# P0-5: credential inventory populated
docker exec ai-gateway-postgres-1 psql -U litellm -d litellm -c \
  'SELECT credential_id, provider, status FROM credential_inventory LIMIT 5;'
```

## Unblock procedure

1. Update each row **Status** to Done with PR/issue link.
2. Post checklist completion on Epic #38 GitHub issue.
3. Open atomic child issues 38-2 through 38-4 for claiming per REPO_IMPROVEMENT_WORKFLOW.md.
