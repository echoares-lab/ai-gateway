# Implementation Plan: Admin Console Tenant/Team Panel

## Goal
Add a tenant/team view to the unified admin console, enabling operators to surface per-tenant/team usage, quota, and credential health.

## Proposed Implementation Plan

### Phase 1: Data Contract Audit
1.  Review `services/gateway-engine/admin_api.py` and current LiteLLM integration to understand how to fetch consolidated tenant data.
2.  Define the API response structure for the new `/admin/tenants` endpoint, reusing the data contract from existing status aggregators.

### Phase 2: Implementation
1.  **Backend API:** Add a new endpoint `/admin/tenants` in `services/gateway-engine/admin_api.py` (or `main.py`) that aggregates data from LiteLLM team information and credential inventory.
2.  **UI Integration:** Update the Admin Dashboard HTML template (or the client-side component) to include a new "Tenants" panel displaying the aggregated data.

### Phase 3: Testing & Validation
1.  **Integration Test:** Add a test case to `services/gateway-engine/test_gateway_engine_admin_api.py` to verify the new endpoint returns correct tenancy data.
2.  **Verification:** Ensure the UI correctly parses and renders the new data.

---
**Approval Needed:** Please review this plan. If approved, I will begin Phase 1: Data Contract Audit.
