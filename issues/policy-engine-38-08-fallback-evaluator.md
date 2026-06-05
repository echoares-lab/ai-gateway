---
work_type: type:feature
summary: Layered fallback rule evaluator — capability filter, policy allowlist, affinity lock, health scoring, cost tier, YAML baseline.
problem: |
  Static litellm-config.yaml fallback matrices cannot adapt to request shape, health
  scores (#60), cooldown state, or budget pressure.
why_now: |
  Central routing brain requires dynamic ordered_deployments replacing static-only fallbacks.
scope: |
  - Rule layers per POLICY_ENGINE_AND_ROUTING_REFACTOR.md §5.5 (ordered evaluation)
  - Integrate 38-5 repo allowlist, 38-6 family lock, 38-7 cooldown skip
  - Health-weighted order via #60 scoring when eligible
  - Cost tier preference when team_budget_pct_used > 80%
  - Static YAML baseline as final safety net
  - quota_aware_mode influences credential ordering in chain metadata
non_goals:
  - Custom policy DSL
acceptance:
  - [x] Tools present → non-tool models removed (capability hard filter)
  - [x] All-cooldown credentials skipped in ordered_deployments
  - [x] Agent affinity + tools → no cross-family unless policy allows
  - [x] rules_applied lists layer tags in evaluation order
tests: |
  Gate A: rule ordering fixture tests
  Gate B: mock integration policy × static fallbacks
  Gate C: run-e2e failover matrix (label)
risks: |
  LiteLLM dynamic fallback API gaps — verify pinned version; see litellm-upgrade.md.
dependencies:
  - policy-engine-38-05-repo-affinity.md
  - policy-engine-38-06-agent-affinity.md
  - policy-engine-38-07-rate-limit-aggregator.md
  - issues/policy-engine-phase0-prerequisites.md (P0-2, P0-3)
files:
  - services/policy-engine/evaluator/fallback.py
  - services/policy-engine/main.py
claim_status: done
blocks:
  - policy-engine-38-16-audit-log.md
  - policy-engine-38-17-integration-tests.md
blocked_by:
  - policy-engine-38-05-repo-affinity.md
  - policy-engine-38-06-agent-affinity.md
  - policy-engine-38-07-rate-limit-aggregator.md
execution_notes: |
  Quota-aware deprioritized credentials must affect deployment ordering before health scoring.
github_issue: #127
---

# 38-8 — Fallback Rule Evaluator

## Closeout

- **Claim-ID:** cursor-policy-fallback-eval-20260605T055013Z
- **Status:** done
- **PR:** https://github.com/echoares-lab/ai-gateway/pull/144
- **Files:** `evaluator/fallback.py`, `main.py`, `test_fallback.py`
- **Tests:** 10/10 `test_fallback.py` pass; 83/83 policy-engine suite pass
