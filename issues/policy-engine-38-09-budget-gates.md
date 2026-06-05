---
work_type: type:feature
summary: Account budget gates — LiteLLM team hard gate + soft quota headroom deprioritization.
problem: |
  Team RPM/TPM/dollar budgets and per-credential quota headroom are not enforced before
  provider calls. Exhausted OAuth accounts still receive traffic until hard 429.
why_now: |
  Cost control and quota-aware routing require budget snapshot in RoutingContext and
  gate/throttle actions in RoutingDecision.
scope: |
  - Hard gate: gate=deny + retry_after when team budget exhausted (LiteLLM native)
  - Soft gate: deprioritize credentials below N% quota headroom (QuotaHeadroom)
  - Budget-aware routing: cheaper tier when team_budget_pct_used > 80%
  - Optional credential reservation token bucket for high-priority repos
  - Populate budget snapshot in translator → RoutingContext
non_goals:
  - Full chargeback platform (38-21)
  - Policy-engine-only hard gate without LiteLLM (open question #5 in design doc)
acceptance:
  - [x] Exhausted team budget → gate=deny with deny_reason
  - [x] Low headroom credential in deprioritized_credentials (soft gate)
  - [x] rules_applied includes budget:soft_deprioritize / budget:hard_deny
  - [x] QuotaHeadroom threshold configurable per pool in policy_json
tests: |
  Gate A: budget gate unit tests
  Gate B: mock integration budget exhaustion
risks: |
  Double-gating with LiteLLM if both enforce. Coordinate placement per open question #5.
dependencies:
  - policy-engine-38-04-translator.md
  - issues/policy-engine-phase0-prerequisites.md (P0-4 TENANCY-3)
files:
  - services/policy-engine/evaluator/budget.py
  - services/translator/translator.py
claim_status: done
blocks: []
blocked_by:
  - policy-engine-38-04-translator.md
  - issues/policy-engine-phase0-prerequisites.md
execution_notes: |
  **Quota-aware:** QuotaHeadroom from credential_inventory.metadata + CLIProxy quota-summary.
  Soft gate aligns with quota-aware pre-emptive strategy (38-7).
  **Shipped:** `evaluator/budget.py` — soft deprioritize always on; hard deny fail-open until P0-4
  (`BUDGET_HARD_GATE_ENABLED` or `policy_json.budget.hard_gate_enabled`). PR pending.
github_issue: #128
---

# 38-9 — Account Budget Gates (Quota Headroom)
