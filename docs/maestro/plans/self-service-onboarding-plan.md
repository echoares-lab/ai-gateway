# Implementation Plan: Self-Service Onboarding Flow

## Goal
Transform the operator-centric `setup-repo-env.sh` bootstrap flow into an automated, self-service registration and validation flow for new repositories and AI clients.

## Proposed Implementation Plan

### Phase 1: Registration API & Contract
1.  **Define Registration Schema:** Create a JSON schema for repository registration (repo name, team slug, client profile).
2.  **API Endpoint:** Implement `/onboarding/register` in `gateway-engine/admin_api.py` that validates the request against tenancy constraints and reserves necessary config slots.

### Phase 2: Automated Key Provisioning
1.  **Credential Generation:** Integrate with `services/gateway-engine/admin_api.py` (and LiteLLM) to automatically generate keys following the naming convention `ak-{org}-{workspace}-{team}-{repo}-{env}` upon registration.
2.  **Client Profiles:** Define configuration templates for different AI clients (Cursor, Claude Code, etc.) to be returned by the onboarding API.

### Phase 3: Connectivity Validation
1.  **Validation Helper:** Implement a lightweight probe utility that attempts a dummy request using the newly generated keys to verify gateway connectivity.
2.  **Automated Status Reporting:** The onboarding flow will return the connectivity validation result to the user.

### Phase 4: Testing & Integration
1.  **Unit Tests:** Verify the registration API and credential generation logic.
2.  **End-to-End Validation:** Create a mock repository onboarding test to ensure the full flow (registration -> key gen -> validation) works seamlessly.

---
**Approval Needed:** Please review this plan. If approved, I will begin Phase 1: Registration API & Contract.
