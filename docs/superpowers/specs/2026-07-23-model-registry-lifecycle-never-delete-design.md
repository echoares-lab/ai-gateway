# Model Registry Lifecycle (Never-Delete) Design

**Status:** Approved design

**Date:** 2026-07-23

**Repository:** `echoares-lab/ai-gateway`

**Related:** [Automatic Model Reconciliation and Stable Key Escrow](./2026-07-22-automatic-model-reconciliation-and-key-escrow-design.md)

## Context and Problem

Automatic model reconciliation is live: CLIProxy discovery, probing, demand-triggered refresh, and LiteLLM apply via `/model/new` all work. The remaining product gap is the **enable gate**.

Today, newly discovered (and retryable disabled) models become `enabled=true` only when `probe_status == "healthy"`. Transient upstream failures (`rate_limited` / 429, timeouts, 5xx) leave models like `gpt-5-6-luna|sol|terra` in the registry but **not advertised**. Clients then receive hard `Invalid model name` errors, so LiteLLM fallbacks / smart routing never run.

That contradicts the purpose of routing: a named alias should exist in the catalog so degraded primaries can fall through to healthy peers.

Separately, vocabulary is overloaded: `enabled` currently means both “passed a healthy probe” and “present in the live catalog.” Soft disable and hard delete coexist; hard delete fights durable metrics, attribution, and auditability.

## Goals

- Never hard-delete registry rows in normal operations.
- Advertise models as soon as they are known from trusted discovery, including on transient probe failure.
- Keep probe health informational (`HEALTHY` / `UNHEALTHY`) rather than a catalog membership gate (except authoritative absence / missing-model for *new* rows).
- Auto-attach default cross-family fallbacks when curated fallbacks are absent; curated metadata always wins later.
- On discovery absence: alert via Prometheus + Alertmanager (≈ daily), keep advertised, auto-retire after a long grace period (~30 days).
- Demand-triggered reconciliation never retires models.
- Preserve a compatibility shim so existing `enabled` readers keep working during migration.

## Non-goals

- Inventing models that CLIProxy does not advertise.
- Synchronous request-path catalog mutation.
- Replacing curated routing/policy metadata with discovery guesses.
- Implementing Alertmanager routing trees outside this repo’s metric/contract (rules may live in the observability/gitops repo; this design defines metric names and alert intent).
- Immediate hard-removal of the admin `?hard=true` code path without a follow-up deprecation note (default behavior becomes reject / break-glass).

## Glossary

| Term | Meaning |
|------|---------|
| **Discover** | Read trusted CLIProxy `/v1/models` and normalize into registry candidates. |
| **Registry row** | Durable Postgres `model_registry` record. Permanent under this design. |
| **Canonical id** | Registry primary key / LiteLLM `model_name` (e.g. `gpt-5-6-sol`). |
| **Upstream id** | Exact CLIProxy model id used for probes and `litellm_params.model` (e.g. `gpt-5.6-sol`). |
| **Alias** | Additional client-facing names (`AI-Gateway:…`, dotted forms). |
| **Probe** | Health check against the upstream id (before or without requiring a LiteLLM alias). |
| **Probe status** | Last probe outcome class: `healthy`, `rate_limited`, `timeout`, `temporarily_unavailable`, `missing_model`, `auth_failure`, `error`, … |
| **Registry status** | Coarse row state: `PENDING`, `HEALTHY`, `UNHEALTHY`, `RETIRED`. |
| **Advertised** | Included in the live apply set and `/v1/models` catalog. |
| **Routable** | Requests naming the model are accepted; may succeed via primary or fallback. |
| **Primary** | Preferred upstream target for the alias. |
| **Fallback** | Ordered substitutes when the primary fails. |
| **Apply** | Push the advertised set into LiteLLM (runtime `/model/new` and/or rendered artifacts). |
| **Demand reconcile** | Expedited refresh after an authenticated unknown-model error; hint only, never invents ids, never retires. |
| **Retire** | Set `retired=true` and stop advertising; row retained forever. Reversible on rediscovery or operator action. |
| **Absence** | Model previously known, not present in the latest discovery set. |
| **Curated metadata** | Operator/policy fields (cost, capabilities, `fallbacks`, etc.) that discovery must not wipe. |
| **Enabled (compat)** | Legacy boolean meaning `advertised && !retired`. |

## Lifecycle States

```text
UNKNOWN ──discover──► PENDING ──probe──► READY ──apply──► ADVERTISED
                         │                  │                  │
                         │                  │                  ├─ primary OK ──► SERVING
                         │                  │                  └─ primary bad + fallbacks ──► SERVING_DEGRADED
                         │                  │
                         │                  └─ operator / 30d absence ──► RETIRED
                         │
                         └─ missing_model on first probe (new row) ── stay unadvertised / PENDING→unadvertised

RETIRED ──rediscover or operator──► PENDING / READY   (same row)
```

| State | In registry | Advertised | Routable | Notes |
|-------|-------------|------------|----------|-------|
| **PENDING** | yes | no | no | First seen; probe incomplete |
| **READY** | yes | not yet / about to | no until apply | Known; may be unhealthy |
| **ADVERTISED** | yes | yes | yes | In catalog |
| **SERVING** | yes | yes | yes | Primary healthy |
| **SERVING_DEGRADED** | yes | yes | yes via fallback | Primary transiently bad |
| **RETIRED** | yes | no | no | Never deleted |

`SERVING` / `SERVING_DEGRADED` are observational labels derived from `advertised` + `probe_status` (+ fallback presence); they need not be stored as separate DB enums if `status` + flags suffice.

## Decisions (locked)

1. **Advertise on first successful discovery path even when probe is transient** (`rate_limited`, `timeout`, `temporarily_unavailable`, and similar retryable classes). Health stays `UNHEALTHY` when appropriate.
2. **Default cross-family fallbacks** attach at render/apply time when the row has no curated `fallbacks`. When curated fallbacks exist, they win. Discovery never overwrites curated fallbacks with defaults or empties.
3. **Never hard-delete** in normal ops. Soft end-of-life is **retire**.
4. **Absence policy:** keep advertised; set `absent_since` on first continuous miss; clear on rediscovery; **auto-retire after 30 days**; Prometheus metrics + Alertmanager alerts (~daily repeat while absent).
5. **Demand runs never retire.**
6. **Implementation approach:** explicit lifecycle fields (`advertised`, `retired`, `absent_since`) with `enabled` as a compatibility shim.

## Data Model

Add (or map) fields on `model_registry`:

| Field | Type | Meaning |
|-------|------|---------|
| `advertised` | bool | In live catalog / apply set |
| `retired` | bool | Retired; must not advertise |
| `absent_since` | timestamptz null | Start of continuous discovery absence |
| `status` | text | Includes `RETIRED` |
| `probe_status` / `probe_http_status` / `probe_checked_at` | existing | Unchanged role |
| `policy_metadata.fallbacks` | list (curated) | Optional; wins over defaults |

**Compatibility:**

- Read: `enabled := advertised && !retired`
- Write of legacy `enabled=true`: set `advertised=true`, `retired=false`
- Write of legacy `enabled=false`: set `advertised=false` (prefer also setting `retired=true` for operator soft-delete via admin API)

Migration for existing rows:

- `enabled=true` → `advertised=true`, `retired=false`
- `enabled=false` → `advertised=false`, `retired=false` initially (so retryable models can advertise on next reconcile without requiring a separate un-retire). Operator-disabled rows that used `status=DISABLED` → `retired=true`, `advertised=false`.

## Reconciliation Behavior Changes

### Probe → advertise gate

Replace:

```text
probe_succeeded = (probe_status == "healthy")
advertised/enabled = probe_succeeded   # for additions / retryable
```

With:

```text
retryable_transient = probe_status in {rate_limited, timeout, temporarily_unavailable, transient, ...}
authoritative_missing = probe_status in {missing, missing_model}

if addition or retryable_unadvertised:
  if authoritative_missing:
    advertised = false
  elif healthy or retryable_transient:
    advertised = true
  else:  # hard error / auth_failure — keep unadvertised until reviewed or later policy split
    advertised = false
status = HEALTHY if healthy else UNHEALTHY (unless retired)
```

Already-advertised models: transient probe failures **must not** un-advertise (preserves today’s “don’t disable on 429” rule).

### Fallbacks at render

When building LiteLLM fallbacks for an advertised model:

1. If curated `policy_metadata.fallbacks` is a non-empty list, filter to advertised non-self targets and use it.
2. Else apply **default cross-family map** (config-driven), e.g. GPT family → preferred Gemini → Claude peers that are currently advertised.
3. Discovery merge must not clear curated fallbacks.

### Absence / retire

On each **scheduled** (and startup/manual) discovery diff:

- Present in discovery → `absent_since = null`
- Missing from discovery, row exists, not retired → if `absent_since` is null, set to now; else keep
- If `absent_since` age ≥ `ABSENCE_RETIRE_DAYS` (default 30) → `retired=true`, `advertised=false`, `status=RETIRED`

Demand triggers may update discovery and clear absence on rediscovery but **must not** evaluate the retire timer.

### Apply set

Apply / catalog verification expects models where `advertised && !retired`. Probe health is not an apply precondition.

## Observability

### Metrics (gateway-engine)

Low-cardinality labels only (`model_id`, `family`, bounded `probe_class`):

| Metric | Type | Meaning |
|--------|------|---------|
| `gateway_model_absent` | gauge 0/1 | Known row missing from latest discovery |
| `gateway_model_absent_days` | gauge | Days since `absent_since` |
| `gateway_model_advertised` | gauge 0/1 | Advertised flag |
| `gateway_model_retired` | gauge 0/1 | Retired flag |
| `gateway_model_probe_status` | gauge / enum label | Last probe class |

No secrets, tokens, or raw upstream bodies as labels.

### Alertmanager intents

| Alert | Condition (intent) | Behavior |
|-------|--------------------|----------|
| `GatewayModelAbsent` | absent for >1h while not retired | Notify; repeat ≈ daily |
| `GatewayModelPendingRetire` | `absent_days >= ABSENCE_ALERT_PENDING_DAYS` (default 25) | Heads-up before auto-retire |
| `GatewayModelAutoRetired` | retired due to absence policy | Confirm retirement |

Exact PromQL and receiver config live with the observability stack; this design owns metric contracts and alert names/intent.

## Admin API Compatibility

| API | New behavior |
|-----|----------------|
| `DELETE /admin/models/{id}` | Retire (`retired=true`, `advertised=false`); never delete row |
| `DELETE /admin/models/{id}?hard=true` | Reject by default (410/400 with typed error); optional break-glass flag later |
| Status counts | Expose `advertised`, `retired`, `absent`; keep `enabled`/`disabled` aliases for one release |
| Reconcile status | Unchanged trigger/phase model; counts use new semantics |

## Configuration

| Variable | Default | Purpose |
|----------|--------:|---------|
| `GATEWAY_ENGINE_MODEL_ABSENCE_RETIRE_DAYS` | `30` | Continuous absence before auto-retire |
| `GATEWAY_ENGINE_MODEL_ABSENCE_ALERT_PENDING_DAYS` | `25` | Pending-retire alert threshold |
| Default fallback map | GPT→Gemini→Claude (configurable) | Used only when curated fallbacks absent |

Existing reconciliation knobs (interval, expedited min interval, probe stale age, timeout) remain.

## Interaction with Prior Design

This amends [2026-07-22 automatic reconciliation](./2026-07-22-automatic-model-reconciliation-and-key-escrow-design.md) safety rules:

- Keep: discovery does not wipe curated metadata; demand does not invent models; atomic apply + rollback; demand rate limits.
- Change: “new additions remain disabled until healthy probe” → “advertise on transient probes; health is informational.”
- Clarify: “429 never disables” extends to **first advertise** as well as preserving already-advertised rows.
- Add: never-delete + absence grace + Prom/AM alerts + retire after 30 days.
- Add: default fallbacks until curated exist.

Key escrow sections of the prior design are unchanged.

## Rollout

1. Schema migration + compat shim (`enabled` mapping).
2. Reconciliation gate change + default fallback render + unit tests.
3. Absence tracking + retire timer (scheduled only) + metrics.
4. Alertmanager rules in observability gitops.
5. Deprecate hard delete in admin API.
6. Verify live: demand for `gpt-5-6-sol` results in advertised alias and fallback path under Cliproxy 429.

## Test Plan (design-level)

- New discovery + `rate_limited` probe → `advertised=true`, `status=UNHEALTHY`, present in apply set.
- New discovery + `missing_model` → not advertised.
- Already advertised + later `rate_limited` → remains advertised.
- No curated fallbacks → default cross-family attached; curated list later replaces defaults and survives rediscovery.
- Absence day 0 → metric absent=1, still advertised; day 30 scheduled run → retired; demand run at day 30 does not retire.
- Rediscovery before day 30 clears `absent_since`.
- Rediscovery after retire clears retire and re-enters advertise path.
- Admin DELETE retires; hard delete rejected.
- Compat: legacy `enabled` read matches `advertised && !retired`.

## Open Follow-ups (out of scope for initial land)

- Per-family default fallback matrix polish.
- Break-glass hard delete under explicit env flag.
- Admin UI copy updates for advertised/retired vs enabled.
