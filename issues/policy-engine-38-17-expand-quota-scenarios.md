---
work_type: type:test
summary: Expand 38-17 policy × failover integration matrix with quota-aware scenarios.
claim_status: claimed-by-cursor-policy-failover-expand
parent: policy-engine-38-17-integration-tests.md
acceptance:
  - [x] 429 preemptive deprioritizes credentials and skips cooled-down deployments
  - [x] Translator prometheus rate-limit signals trigger preemptive path without agent fixture
  - [x] Budget hard deny surfaces gate, retry_after, and admin trace
  - [x] Cooldown skip removes rate-limited fallback from ordered chain
  - [x] Inventory exclude deprioritizes degraded credentials from routing
  - [x] 0 skips in mock integration job
files:
  - tests/integration/test_policy_failover.py
  - tests/mock-upstream/app.py
  - tests/mock-policy-engine/app.py
---

# 38-17 expand — Quota-aware policy failover scenarios

Follow-up to scaffold in PR #158. Deepens Gate B coverage for quota-aware routing paths documented in RUNBOOK.md and ROUTING_AND_FAILOVER_STRATEGY.md §3.
