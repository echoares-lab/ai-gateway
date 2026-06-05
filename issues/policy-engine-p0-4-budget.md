---
work_type: type:feature
summary: P0-4 — LiteLLM team RPM/TPM/dollar budget enforcement from workspace rules.
claim_status: claimed-by-cursor-575k-20260605
claimed_by: cursor-575k-20260605
claim_status: done
acceptance:
  - [x] workspace-rules.yaml defines defaults + per-team RPM/TPM/max_budget
  - [x] setup_litellm_teams.py applies budgets on create and update
  - [x] translator populates budget in RoutingContext
  - [x] BUDGET_HARD_GATE_ENABLED passed to policy-engine service
  - [x] Unit tests for workspace rules and budget snapshot parsing
dependencies:
  - issues/policy-engine-phase0-prerequisites.md (P0-4)
  - issues/policy-engine-38-09-budget-gates.md
  - docs/TENANCY.md
---

# P0-4 — LiteLLM Team Budget Enforcement (TENANCY-3)

**Claim-ID:** cursor-575k-20260605

Provision: `python setup_litellm_teams.py --org echoares --workspace core --team eng`

Enable hard deny: `BUDGET_HARD_GATE_ENABLED=true` after budgets are provisioned.
