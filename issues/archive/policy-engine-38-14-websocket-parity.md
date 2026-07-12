---
work_type: type:feature
summary: Codex WebSocket policy parity — evaluate path for /v1/responses WS or document explicit bypass.
problem: |
  Codex /v1/responses WebSocket bypasses LiteLLM and policy-engine evaluate path.
  Routing decisions do not apply to WS traffic.
why_now: |
  Phase 3 — parity or documented bypass required before production policy enforcement.
scope: |
  - Option A: Build RoutingContext + evaluate for WS upgrade path in gateway-engine
  - Option B: Document explicit bypass in POLICY_ENGINE_AND_ROUTING_REFACTOR.md + CLIENT_COMPATIBILITY.md
  - If parity: inject session_key and quota_aware hints into WS upstream metadata
non_goals:
  - Blocking WS traffic until parity ships
acceptance:
  - [x] Decision documented in design doc §9 WebSocket row
  - [ ] If parity: WS requests receive RoutingDecision metadata
  - [x] If bypass: admin console shows WS bypass flag (38-15)
tests: |
  Gate A: WS routing unit tests or bypass assertion tests
  Gate C: Codex WS smoke if parity chosen
risks: |
  WS latency budget tighter than HTTP evaluate SLA.
dependencies:
  - policy-engine-38-04-gateway-engine.md
files:
  - services/gateway-engine/main.py
  - docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md
claim_status: done
claimed_by: cursor-575k-20260605T060900Z
blocks:
  - policy-engine-38-17-integration-tests.md
blocked_by:
  - policy-engine-38-04-gateway-engine.md
execution_notes: |
  Quota-aware applies to WS if parity — same deprioritized_credentials semantics.
github_issue: #133
---

# 38-14 — WebSocket Policy Parity

**Decision:** Option B — explicit bypass (default). Optional `POLICY_ENGINE_WS_EVALUATE` hook
for future parity after 38-04 ships.

**PR:** (pending)
