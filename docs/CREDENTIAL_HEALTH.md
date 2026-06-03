# Credential Inventory, Health States & Remediation Design

> **Status:** Design. Foundational model for [Roadmap Epic #33 - Credential pool orchestration and account health automation](https://github.com/echoares-lab/ai-gateway/issues/33).
> This document defines the credential identity model, outlines the health state machine, details remediation & alerting strategies, and presents a phased implementation plan.

---

## 1. Credential Identity & Inventory Model

To track and manage the provider accounts used by the gateway, we define a structured **Credential Inventory Model**. A credential represents an active authorization lease with a downstream provider.

### 1.1 Credential Fields

| Field | Type | Description |
|---|---|---|
| `credential_id` | String | Unique identifier (e.g. `cred-echoares-anthropic-01`). |
| `provider` | Enum | Downstream provider (`openai`, `anthropic`, `gemini`, `xai`). |
| `label` | String | Operator-friendly description of the account lease owner. |
| `key_fingerprint` | String | SHA-256 hash prefix of the credentials (secrets are NEVER stored in plain text in logs or inventory lists). |
| `status` | Enum | The current health state: `HEALTHY`, `DEGRADED`, `CRITICAL`, `EXPIRED`, `SUSPENDED`. |
| `cool_down_until` | Timestamp | Timestamp indicating when the credential is ready to receive traffic again after a rate limit (429) cooldown. |
| `consecutive_failures`| Integer | Counter of sequential connection/upstream errors. |
| `metadata` | JSON | Provider-specific info (e.g., token usage, tier limits, billing alert settings). |

---

## 2. Health State Machine

Downstream API keys transition through a defined lifecycle based on real-time traffic signals (latency, error rates, status codes):

```text
       [ HEALTHY ]
             |
  (Success / | (429 / 503 /
   Cooldown  |  Rate Limit)
     Ends)   |
             v
 [ SUSPENDED ]   [ DEGRADED ]
       ^                 |
       |                 |
  (Invalid Key /   (Consec. Fails
   Auth Failure)    Exceed Limit)
       |                 |
       [ CRITICAL ] <----/
```

### 2.1 State Definitions

1. **HEALTHY:** The credential is fully active, responding with `200 OK`, and eligible to receive prompt traffic.
2. **DEGRADED:** The credential has experienced transient rate limits (HTTP 429) or service outages (HTTP 503/504). It is cooled down and bypassed for a configured period (e.g. 60 seconds).
3. **CRITICAL / EXPIRED:** The credential has exceeded consecutive failure limits (e.g., 3 failed calls) or returns deterministic API authentication errors (HTTP 401 Unauthorized, Invalid Key). It is automatically removed from active rotation.
4. **SUSPENDED:** The operator has manually deactivated the key, or it has been flagged for billing/compliance review.

---

## 3. Remediation & Alerting Plan

When a credential health state transitions to `DEGRADED` or `CRITICAL`, the gateway automatically triggers remediation actions:

### 3.1 Automatic Remediation
- **Transient Failures (429/503):** Trigger LiteLLM-native cooldown loops. LiteLLM temporarily excludes the model deployment from active load balancing for `cooldown_time` (default: 60s).
- **Hard Failures (401/Invalid Key):** Mark the credential database record as suspended. Disable the associated LiteLLM model group fallback node and reload the config.

### 3.2 Alerting & Telemetry
- **Alert Channels:** Dispatch structured JSON payloads to operators via configured Webhook URLs (e.g. Slack, MS Teams).
- **Alert Payload Schema:**
  ```json
  {
    "event": "credential_critical",
    "credential_id": "cred-echoares-anthropic-01",
    "provider": "anthropic",
    "reason": "401 Unauthorized / Invalid Key",
    "timestamp": "2026-06-02T13:45:00Z"
  }
  ```

---

## 4. Current Data Sources & Gaps

We identify how credentials and their states are currently stored across the repository:

### 4.1 Data Sources
- **CLIProxy Configurations:** Stored in `{HOME}/.cli-proxy-api/config.yaml` or `/home/dev/.cliproxy/config.yaml`. Contains API keys for oauth-backed CLI profiles.
- **LiteLLM Database:** SQLite/Postgres `LiteLLM_VerificationTokenTable` manages virtual client keys.

### 4.2 Gap Analysis
- No unified inventory database: Credentials are split between file configurations (`litellm-config.yaml`) and database schemas.
- Lack of active monitoring: Gateway does not perform background validation/probing of credentials, relying entirely on passive traffic logs.

---

## 5. Phased Implementation Plan

We propose splitting the execution of Epic #33 into the following sequenced child issues:

1. **feat(credentials-schema): implement read-only credentials status database table**
   Add a PostgreSQL schema migration and migration runner to store the credential inventory list and their active health states.
2. **feat(credentials): add background health-check probing service**
   Implement a lightweight, isolated cron-like background worker that performs periodic health checks against downstream provider endpoints (using `/v1/models` or simple completions).
3. **feat(credentials): implement Slack alerting webhook on state change**
   Add an alerting callback function that fires webhook notifications whenever a credential shifts to `CRITICAL` or `DEGRADED`.

---

## 6. References
- [Tenancy & Workspace Domain Model](./TENANCY.md)
- [Client Compatibility Matrix](./CLIENT_COMPATIBILITY.md)
- [Roadmap Status](./ROADMAP.md)
- [Architecture Decision Record - MCP Control Plane](./ARCHITECTURE.md)
