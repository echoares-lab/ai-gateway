---
work_type: type:feature
summary: Gateway Engine integration — POLICY_ENGINE_ENABLED flag, evaluate call, metadata injection, fail-open.
claim_status: in_progress
claimed_by: cursor-575k-20260605T120000Z
github_issue: #123
execution_notes: |
  Phase 0 partial gate: P0-1 done; P0-2/P0-3 in progress — POLICY_ENGINE_ENABLED defaults false.
acceptance:
  - [x] Feature flag off → no policy-engine HTTP calls
  - [x] Feature flag on → decision in forwarded LiteLLM metadata
  - [x] Fail-open verified by unit test (policy-engine down)
  - [x] RoutingContext includes quota_headroom when inventory available
---
# 38-4 — Gateway Engine Integration
