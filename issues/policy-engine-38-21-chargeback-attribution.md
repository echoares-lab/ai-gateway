---
work_type: type:docs
summary: Chargeback attribution — spend by repo/agent via routing_decisions_log + Langfuse.
problem: |
  Gateway spend is visible per model/team in LiteLLM but not chargeback-ready per
  repo or agent session. Finance and platform teams cannot allocate LLM costs to
  repositories or automation agents.
why_now: |
  Phase 5 optional. Audit log (38-16) stores repo/agent context; TENANCY.md
  defines Langfuse metadata tags; TOKEN_USAGE_ANALYTICS.md sketches cost panels.
scope: |
  - Design doc: docs/CHARGEBACK_ATTRIBUTION.md
  - policy_json.chargeback schema (rollup schedule, environment filters)
  - Join model: routing_decisions_log.request_id ↔ Langfuse trace metadata
  - Phased implementation breakdown (5b–5e)
non_goals:
  - Invoice generation or external billing integration
  - Real-time per-request cost enforcement (38-09 budget gates)
  - Eval-driven routing (38-19)
acceptance:
  - [x] Repo/agent spend attribution model documented
  - [x] Join path between audit log and Langfuse identified
  - [x] policy_json.chargeback schema sketched
  - [x] Phased implementation issues outlined
tests: |
  N/A — design stub only (Gate A docs lint if wired in CI)
risks: |
  Missing request_id on Langfuse traces forces weaker metadata-only joins —
  translator propagation (5b) is prerequisite for accurate agent attribution.
dependencies:
  - issues/policy-engine-38-16-audit-log.md
  - docs/TENANCY.md
  - docs/TOKEN_USAGE_ANALYTICS.md
files:
  - docs/CHARGEBACK_ATTRIBUTION.md
  - issues/policy-engine-38-21-chargeback-attribution.md
claim_status: in-review
blocks: []
blocked_by: []
execution_notes: |
  Design stub acceptable per Phase 5 dispatch. Nightly rollup and admin panel
  deferred until request_id propagation (5b) and 38-04 translator wire stabilize.
github_issue: #140
---

# 38-21 — Chargeback Attribution (Optional)

**Epic:** [#38](https://github.com/echoares-lab/ai-gateway/issues/38)  
**Design:** [docs/CHARGEBACK_ATTRIBUTION.md](../docs/CHARGEBACK_ATTRIBUTION.md)

## Claim

- **Claim-ID:** cursor-chargeback-20260605T060500Z
- **Branch:** `feat/chargeback-attribution`
- **Worktree:** `/home/dev/.cursor/worktrees/ai-gateway__SSH__dev_/575k`
- **Scope:** Design/docs stub — spend attribution by repo/agent using audit log + Langfuse

**PR:** https://github.com/echoares-lab/ai-gateway/pull/150
