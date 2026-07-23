# Automatic Model Reconciliation and Stable Key Escrow Design

**Status:** Approved design

**Date:** 2026-07-22

**Repository:** `echoares-lab/ai-gateway`

## Context and Root Cause

The gateway already has registry-backed CLIProxy discovery, probing, rendering, and reconciliation APIs. Automatic operation was nevertheless lost through two deliberate removals:

1. Request-path auto-provisioning was removed because unauthenticated traffic could mutate the catalog, generic inferred metadata was unsafe, and implicit changes concealed configuration drift.
2. `sync-models` was removed from the legacy host's weekly `apply` cron after production moved to k3s. The replacement k3s-owned scheduler or deployment-pipeline trigger was never added.

Consequently, CLIProxy and a newly updated client can know about a model before the registry and LiteLLM do. This produced the observed failure where Codex requested `gpt-5.6-sol` while the gateway exposed only older GPT aliases.

Separately, gateway-created LiteLLM virtual keys are returned once and cached only by `ai-launcher`. Loss of that local cache leaves a stable remote alias without recoverable local key material. Rotation is prohibited because key identity is used for durable metrics and attribution.

## Goals

- Restore automatic model discovery and reconciliation without synchronous request-path mutation.
- Reconcile shortly after startup, periodically, and promptly after an unknown-model request.
- Preserve curated registry metadata and avoid destructive action on transient failures.
- Make reconciliation state observable and auditable.
- Normalize client, registry, LiteLLM, and CLIProxy model identifiers consistently.
- Store launcher-managed virtual-key secrets in OpenBao and return the same secret when a launcher cache is lost.
- Never automatically rotate or delete an existing key during recovery.

## Non-goals

- Allowing arbitrary client requests to add unrestricted provider models.
- Replacing the registry with CLIProxy's raw catalog.
- Removing `litellm-config.yaml` as a generated compatibility artifact.
- Recovering a historical key secret that was never escrowed and has no surviving copy.
- Exposing OpenBao credentials to `ai-launcher`.

## Automatic Model Reconciliation

### Scheduler

Gateway-engine owns a single background `ModelReconciliationService`. It runs once after application startup dependencies become healthy and then at a configurable interval. Defaults are:

- enabled: true
- startup delay: 30 seconds
- interval: 15 minutes
- expedited-trigger minimum interval: 60 seconds
- reconciliation timeout: 120 seconds

Only one run may execute at a time. Concurrent scheduled, manual, and expedited requests coalesce into one active run plus at most one pending rerun.

The service uses the existing registry APIs internally rather than invoking `cliproxy-setup.sh`. Its phases are:

1. Fetch CLIProxy `/v1/models` using the internal CLIProxy credential.
2. Normalize and validate discovered model identifiers.
3. Upsert discovery state while preserving manually curated metadata.
4. Probe only additions and models whose health state is stale.
5. Render candidate LiteLLM and Gemini resources from enabled registry records.
6. Parse and validate rendered artifacts.
7. Apply changed artifacts atomically.
8. request a bounded LiteLLM reload and verify the reconciled catalog.

A run is successful only when the final advertised catalog contains every newly enabled model expected from the registry.

### Demand-triggered Refresh

When a request fails model resolution with a recognized unknown-model error, gateway-engine submits an expedited reconciliation trigger containing the normalized requested model and client profile. The trigger is asynchronous: it does not mutate configuration inline and does not delay the current request beyond enqueueing bounded in-memory work.

Triggers are accepted only after normal authentication and model-name validation. They are deduplicated by normalized model ID and rate-limited globally. A trigger is a hint to refresh the trusted CLIProxy catalog, not authority to create the requested model. Models absent from CLIProxy remain absent.

The first request may fail, allowing `ai-launcher` to perform its prominent automatic upstream fallback. A later request succeeds after reconciliation if CLIProxy actually advertises and supports the model.

### Safety Rules

- Discovery never overwrites curated cost, capability, routing, or policy metadata with empty or generic values.
- Newly discovered models enter a pending state until validation and required probes succeed.
- HTTP 429, 5xx, timeouts, and credential exhaustion are transient and never remove or disable a model.
- Removal requires the existing consecutive-authoritative-absence policy; demand-triggered runs never remove models.
- Reconciliation uses atomic temporary-file replacement and retains the last known-good artifacts.
- A failed reload or catalog verification restores the last known-good artifacts and reports a degraded run.
- Manual admin sync and reconcile endpoints remain available and share the same service lock and status record.

### Identifier Normalization

Normalization is provider-aware and centralized. It retains the existing external `AI-Gateway:` prefix behavior while mapping client aliases to canonical registry IDs and upstream CLIProxy IDs. Tests explicitly cover dotted and dashed GPT variants, including `gpt-5.6-sol` ↔ `gpt-5-6-sol`, without applying the transformation to unrelated provider identifiers.

The registry record stores the client alias, canonical ID, and upstream ID separately. Rendering uses the LiteLLM-safe alias while `litellm_params.model` uses the exact CLIProxy identifier.

## Reconciliation Observability

Admin status exposes a secret-free model-reconciliation section containing:

- scheduler enabled state and interval;
- current phase and whether a run is active or pending;
- last attempt and last successful completion timestamps;
- trigger source (`startup`, `scheduled`, `demand`, or `manual`);
- discovered, added, updated, enabled, disabled, and unchanged counts;
- requested model for a demand trigger;
- final verification state;
- bounded, redacted error summaries.

Metrics record run duration, outcomes, trigger sources, and change counts. Model IDs may appear only where existing metrics-cardinality policy permits them. Logs never contain provider credentials or virtual keys.

## Stable Launcher Key Escrow

### OpenBao Storage

Gateway-engine is the only component that accesses OpenBao for launcher key escrow. Each stable key is stored at a dedicated versioned KV path derived from a hashed alias, with metadata containing the plaintext alias, LiteLLM key identifier, team ID, creation time, and schema version. The token is stored as a secret field and never appears in logs or metrics.

The k3s workload authenticates directly to OpenBao with a workload-specific Kubernetes-auth or AppRole identity because External Secrets is read-only synchronization and cannot provide runtime escrow writes. OpenBao address, auth mount, role, KV mount, and key prefix are explicit environment settings; no root or broadly scoped token is mounted into the pod.

OpenBao policy grants gateway-engine only create, read, update, and metadata access under the launcher-key prefix. Delete and destroy capabilities are excluded from the runtime policy. Operator migration uses a separate policy.

### Creation Contract

`POST /admin/keys` keeps its existing external purpose but becomes transactional from the caller's perspective. Gateway-engine generates the cryptographically random virtual-key token so it can safely perform write-ahead escrow:

1. Validate the admin identity and request metadata.
2. Reject an alias already present in LiteLLM; do not rotate it.
3. Generate a token with the required LiteLLM virtual-key format using the operating system CSPRNG.
4. Write the token and pending identity metadata to OpenBao.
5. Ask LiteLLM to create the key using that exact token and alias.
6. Verify the token against LiteLLM and mark the escrow record active with the returned LiteLLM key identifier.
7. Return the token only after verification succeeds.

If OpenBao fails before LiteLLM creation, no remote key is created. If LiteLLM creation or verification fails after pending escrow, gateway-engine records a high-severity incomplete-creation condition and returns a non-success response containing no token. It must not silently generate a second key or delete a possibly active LiteLLM identity. Retrying the same alias resumes the pending transaction with the same escrowed token after checking LiteLLM state.

### Recovery Contract

`GET /admin/keys/{alias}/secret` requires the gateway admin key, verifies that the alias exists in LiteLLM, reads the escrow record, checks identity metadata, and returns the original token. Responses use `Cache-Control: no-store` and structured error codes:

- `key_alias_not_found`: no remote alias exists;
- `key_secret_not_escrowed`: alias exists but predates escrow or is incomplete;
- `key_identity_mismatch`: OpenBao metadata does not match LiteLLM identity;
- `secret_store_unavailable`: OpenBao could not be reached safely.

No recovery error causes deletion, regeneration, or rotation.

### Legacy Import

`POST /admin/keys/{alias}/import` is an operator-only migration endpoint. It verifies the supplied original token against LiteLLM before writing it to OpenBao and refuses to overwrite a different escrowed token. This enables one-time migration of pre-escrow keys when their original token still exists in a launcher cache or approved backup.

Keys whose original secret has been irretrievably lost cannot be recovered cryptographically. They require an explicit operator-approved rotation outside this automatic workflow, with corresponding metrics migration planning.

## API and Documentation

New recovery/import endpoints and reconciliation status fields are added to `docs/openapi/gateway-engine.yaml` and the API documentation registry. Error responses are typed and stable enough for launcher branching; callers do not parse human-readable messages.

Operational documentation covers OpenBao policy/bootstrap, legacy imports, incomplete escrow repair, scheduler controls, forced manual reconciliation, rollback, and verification.

## Testing

Gateway unit tests cover scheduler startup, periodic execution, single-flight coalescing, demand rate limiting, provider-aware normalization, metadata preservation, transient probe safety, atomic apply, reload rollback, and final catalog verification.

Mock integration tests run CLIProxy discovery through registry update, render, LiteLLM reload, and advertised-catalog verification. Unknown-model traffic must enqueue a refresh without directly creating the supplied name.

OpenBao tests use an HTTP fake or test double and cover creation, read-back verification, recovery, legacy import, alias mismatch, unavailable storage, redaction, and the absence of runtime delete capability. LiteLLM and OpenBao partial-failure tests verify that no automatic rotation occurs.

Production verification checks scheduler status, forces one no-change reconciliation, confirms a newly discovered model appears in `/v1/models`, and runs Claude, Codex, and Antigravity through `ai-launcher` with per-client gateway attribution.

## Rollout

1. Deploy OpenBao policy and gateway credentials.
2. Deploy escrow endpoints with scheduler disabled; validate new-key escrow and import selected existing launcher keys.
3. Deploy launcher recovery support and no-fallback gateway tests.
4. Enable scheduler in staging and verify no-change plus synthetic-add reconciliation.
5. Enable scheduler in production, initially at a conservative interval.
6. Enable demand-triggered refresh after scheduled reconciliation has remained healthy.

Rollback disables demand triggers and the scheduler while retaining manual registry APIs, last known-good generated artifacts, existing LiteLLM keys, and OpenBao escrow records.
