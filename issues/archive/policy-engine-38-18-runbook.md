---
work_type: type:docs
summary: Operator runbook — policy-engine ops, pool tier promotion, quota-aware tuning, fail-open.
problem: |
  Policy engine evaluators ship without operator procedures for tier promotion, quota-aware
  mode, dependency health, fail-open incidents, or audit sampling.
why_now: |
  Phase 4 observability (38-16 audit log done). 38-15 admin trace blocked on 38-04;
  runbook can ship design-only operator guidance now.
scope: |
  - RUNBOOK.md section: pool tier promotion, quota-aware mode, Redis/Postgres deps
  - Fail-open procedure when policy-engine or stores unavailable
  - Audit sampling and retention (38-16)
non_goals:
  - Admin console policy trace UI (38-15)
  - New policy-engine code paths
acceptance:
  - [x] Pool tier promotion steps documented (Postgres + litellm-config tier aliases)
  - [x] Quota-aware mode enable/disable and trade-offs documented
  - [x] Redis/Postgres dependency checks and degraded-mode behavior documented
  - [x] Fail-open operator procedure documented
  - [x] Audit sampling env vars and retention documented
tests: |
  N/A — documentation only
risks: |
  Procedures may reference features not yet wired in gateway-engine (38-04) — marked design-only.
dependencies:
  - policy-engine-38-16-audit-log.md
  - docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md
files:
  - RUNBOOK.md
claim_status: done
blocks: []
blocked_by:
  - policy-engine-38-15-admin-trace.md
execution_notes: |
  Design-only runbook per dispatch: 38-15 blocked on 38-04. Operator section documents
  target-state procedures aligned with shipped evaluators (38-1..38-12, 38-16).
github_issue: #137
---

# 38-18 — Operator Runbook Extension

**GitHub:** #137  
**PR:** https://github.com/echoares-lab/ai-gateway/pull/151  
**Design:** [docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md](../docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md)
