---
work_type: type:test
summary: Integration tests — policy × failover matrix (mock Gate B + real-provider Gate C subset).
claim_status: claimed-by-cursor-38-17
github_issue: #136
acceptance:
  - [x] Cross-family tool call blocked when agent affinity + tools (regression)
  - [x] 429 fixture triggers deprioritized_credentials in decision
  - [x] 0 skips in mock integration job
files:
  - tests/integration/test_policy_failover.py
  - tests/mock-policy-engine/
---

# 38-17 — Policy × Failover Integration Tests
