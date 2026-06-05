---
work_type: type:observability
summary: Routing decision audit log — routing_decisions_log table writes (optional sampling).
problem: |
  Policy decisions are not persisted for post-incident analysis or chargeback prep.
why_now: |
  Phase 4 observability. Depends on stable evaluator output from 38-8.
scope: |
  - Async write to routing_decisions_log (sampled, e.g. 1% or on deny/throttle)
  - Store context hash, decision JSON, rules_applied, quota_aware_mode
  - Retention policy (e.g. 30d) documented in RUNBOOK
non_goals:
  - Real-time analytics dashboard
acceptance:
  - [ ] Deny/throttle decisions always logged
  - [ ] quota_aware_mode and deprioritized_credentials in stored JSON
  - [ ] Sampling configurable via POLICY_AUDIT_SAMPLE_RATE
tests: |
  Gate A: audit writer unit tests
risks: |
  Postgres write amplification — async queue + sampling.
dependencies:
  - policy-engine-38-08-fallback-evaluator.md
  - policy-engine-38-10-credential-pool-schema.md
files:
  - services/policy-engine/audit.py
  - db/migrations/002_policy_profiles_pools.sql
claim_status: claimed-by-cursor-agent-575k
blocks: []
blocked_by:
  - policy-engine-38-08-fallback-evaluator.md
execution_notes: |
  Table defined in migration 002 — wire write path only.
github_issue: #135
---

# 38-16 — Routing Decision Audit Log
