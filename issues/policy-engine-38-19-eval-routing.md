---
work_type: type:docs
summary: Evaluation-driven routing design — quality feedback loop tuning fallback weights (#37).
problem: |
  Fallback ordering optimizes availability and cost, not measured task quality.
  No closed loop from Langfuse outcomes or eval datasets into policy-engine weights.
why_now: |
  Phase 5 optional. Fallback evaluator (38-8) and audit log (38-16) provide hooks;
  roadmap epic #37 defines the quality-loop direction.
scope: |
  - Design doc: docs/EVAL_DRIVEN_ROUTING.md
  - Task categories, KPIs, signal sources, policy_json.eval schema sketch
  - Optional layer 5b placement in fallback evaluator (design only)
  - Phased implementation breakdown (5b–5d)
non_goals:
  - Runtime quality reorder (follow-up 5b)
  - MCP tool visibility (38-20)
  - Chargeback platform (38-21)
acceptance:
  - [x] Evaluation/routing feedback loop concept documented
  - [x] Outcome data requirements identified
  - [x] Candidate KPIs defined
  - [x] Phased implementation issues outlined
tests: |
  N/A — design stub only (Gate A docs lint if wired in CI)
risks: |
  Small sample sizes can destabilize weights — min_samples + guard KPIs required.
dependencies:
  - policy-engine-38-08-fallback-evaluator.md
  - issues/policy-engine-38-16-audit-log.md
files:
  - docs/EVAL_DRIVEN_ROUTING.md
  - issues/policy-engine-38-19-eval-routing.md
claim_status: in-review
blocks: []
blocked_by: []
execution_notes: |
  Design stub acceptable per Phase 5 dispatch. Runtime layer deferred until 38-04
  gateway-engine wire and offline aggregation job (5c).
github_issue: #138
---

# 38-19 — Evaluation-Driven Routing (Optional)

**Epic:** [#38](https://github.com/echoares-lab/ai-gateway/issues/38)  
**Roadmap parent:** [#37](https://github.com/echoares-lab/ai-gateway/issues/37)  
**Design:** [docs/EVAL_DRIVEN_ROUTING.md](../docs/EVAL_DRIVEN_ROUTING.md)

## Claim

- **Claim-ID:** cursor-eval-routing-20260605T055608Z
- **Branch:** `feat/eval-routing`
- **Worktree:** `/home/dev/.cursor/worktrees/ai-gateway__SSH__dev_/575k`
- **Scope:** Design/docs stub — quality feedback loop for fallback weight tuning

**PR:** https://github.com/echoares-lab/ai-gateway/pull/147
