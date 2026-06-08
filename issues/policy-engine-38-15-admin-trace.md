---
work_type: type:observability
summary: Policy decision trace in /admin/status per ADMIN_CONSOLE_DATA_CONTRACT.md.
problem: |
  Operators cannot inspect last RoutingDecision, quota_aware_mode, or deprioritized
  credentials without log diving.
why_now: |
  Production phased enablement blocked until admin trace ships (design doc §11 rollout).
scope: |
  - Extend /admin/status with policy_engine section
  - Last decision sample: rules_applied, quota_aware_mode, deprioritized_credentials
  - POLICY_ENGINE_ENABLED status, policy_version, Redis connectivity
non_goals:
  - Full decision history UI (38-16 audit log)
acceptance:
  - [ ] /admin/status includes policy_engine.enabled and last_evaluate_ms
  - [ ] Quota-aware fields visible when last decision used quota path
  - [ ] Contract updated in ADMIN_CONSOLE_DATA_CONTRACT.md
tests: |
  Gate A: admin status schema tests
  Gate B: mock integration admin endpoint
risks: |
  PII in decision debug — redact session keys in production view.
dependencies:
  - policy-engine-38-04-gateway-engine.md
files:
  - services/gateway-engine/gateway-engine.py
  - docs/ADMIN_CONSOLE_DATA_CONTRACT.md
claim_status: in-review
claimed_by: cursor-575k-20260605
blocks: []
blocked_by:
  - policy-engine-38-04-gateway-engine.md
execution_notes: |
  Required before production POLICY_ENGINE_ENABLED=true per rollout stages.
  Duplicate PR #157 closed; track on PR #156 only.
github_issue: #134
---

# 38-15 — Policy Trace in Admin Console

**PR:** https://github.com/echoares-lab/ai-gateway/pull/156 (bundled with 38-04; [#157](https://github.com/echoares-lab/ai-gateway/pull/157) closed as duplicate)
