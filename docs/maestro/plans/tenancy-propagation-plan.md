# Implementation Plan: Finalize Tenancy Metadata Propagation

## Goal
Ensure consistent propagation of `tenant_id` and `team_id` throughout the `gateway-engine` request lifecycle to support multi-tenancy as defined in Epic #30.

## Current State Analysis
- `services/gateway-engine/core/policy/audit.py` is already tenant-aware.
- Tenancy metadata needs to be consistently available in the `RoutingContext` for all request pathways, including fallbacks and LiteLLM interactions.

## Proposed Implementation Plan

### Phase 1: Context Auditing
1.  **Identify missing propagation paths:** Audit `gateway-engine` code to find where `tenancy` context is lost or not correctly passed to downstream calls (e.g., LiteLLM, Langfuse, policy engine).
2.  **Validate `RoutingContext`:** Ensure `RoutingContext` always carries the full `Tenancy` object.

### Phase 2: Propagation Implementation
1.  **Request Middleware:** Update request middleware to populate the `Tenancy` context from validated credentials (e.g., API key labels `ak-{org}-{workspace}-{team}-{repo}-{env}`).
2.  **Downstream injection:** Update `_proxy_to_litellm` and Langfuse logging to ensure metadata headers/tags are injected.

### Phase 3: Testing & Validation
1.  **Unit Tests:** Add unit tests to `services/gateway-engine/test_gateway_engine_admin_policy_integration.py` to verify that `tenant_id`/`team_id` are correctly preserved across requests.
2.  **End-to-End Verification:** Run a mock request to verify that metadata tags (Langfuse) contain the expected values.

---
**Approval Needed:** Please review this plan. If approved, I will begin Phase 1: Context Auditing.
