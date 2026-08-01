# C-SVC-4 Unified Config Admin API Design

**Status:** Approved design for roadmap promotion and contract-first delivery.

**Decision:** Reframe C-SVC-4 as a disabled-by-default, read-only configuration
snapshot and drift API. Do not revive the stale generic LiteLLM team/key proxy
or introduce configuration mutation.

## Context

The historical `feat/unified-config` branch implemented only a generic proxy for
LiteLLM team and key operations. Those routes already exist in
`services/gateway-engine/admin_api.py`, with stronger stable-key behavior added
since the translator-to-gateway-engine migration. The current gateway also has
an admin dashboard, model registry and reconciliation APIs, a read-only
CLIProxy configuration summary, and client configuration generation.

The remaining operator gap is a canonical, machine-readable configuration
snapshot that explains:

- which configuration sources were inspected;
- which safe structural settings are active;
- whether configured models agree with registry and runtime-visible models;
- which required environment references are present; and
- which sources are missing, invalid, unavailable, or drifting.

The API must not become another configuration source of truth. Git remains
authoritative for structural configuration, while the documented runtime model
registry exception remains authoritative for explicit model overrides.

## Approaches Considered

### Dedicated snapshot endpoint — selected

Add `GET /admin/config` with a versioned response and strict management scope.
This creates a small, explicit security and compatibility boundary and keeps
the existing broad `/admin/status` response stable.

### Extend `/admin/status`

Adding detailed configuration data to the existing status payload would avoid
one route, but would increase payload size, couple release cycles, and inherit
the optional `GATEWAY_ENGINE_ADMIN_READ_AUTH` behavior. This is rejected for a
new configuration surface.

### Revive a generic proxy or writable control plane

The old proxy duplicates existing team/key routes. Writable configuration
would conflict with GitOps promotion and current policy-profile ownership. Both
are rejected. Team/key lifecycle remains C-SVC-3; policy and GitOps mutation
require separate contracts and approval.

## API Contract

### Route and authentication

`GET /admin/config`

The route is available only when
`UNIFIED_CONFIG_ADMIN_API_ENABLED=true`. The default is `false`; when disabled,
the route returns a typed `404` without inspecting sources.

Every enabled request requires:

- `x-admin-key` equal to the configured gateway admin key; and
- `x-management-scope: config:read` exactly.

Missing server-side authentication configuration returns `503`. A missing or
incorrect admin key returns `401`. An incorrect scope returns `403`. Client or
model API keys are never accepted as management credentials. Every response
uses `Cache-Control: no-store`.

### Successful and degraded responses

An authenticated request returns `200` with schema identifier
`config-snapshot.v1`, even when one or more sources are unavailable. Partial
failure is represented by `status: degraded` plus typed, bounded errors so one
source cannot suppress safe information from the others.

The top-level shape is:

```json
{
  "schema": "config-snapshot.v1",
  "status": "ok",
  "generated_at": "2026-08-01T00:00:00Z",
  "sources": [],
  "models": {},
  "routing": {},
  "mcp": {},
  "environment": {},
  "validation": {},
  "drift": {},
  "errors": []
}
```

`generated_at` is supplied by an injectable clock and excluded from semantic
snapshot digest calculation. Collections are deterministically sorted.

### Source provenance

Each source entry contains only:

- stable source identifier such as `litellm-config`, `model-registry`, or
  `runtime-visible-models`;
- source kind such as `deployed-file`, `registry`, or `live-api`;
- status: `ok`, `missing`, `invalid`, or `unavailable`;
- immutable SHA-256 digest of the sanitized structural projection when source
  data is safely available; and
- observation timestamp when applicable.

Filesystem paths, hosts, URLs, credentials, raw source bytes, and raw exception
text are forbidden.

### Allowlisted configuration projection

The snapshot exposes only these structural fields:

- model aliases and their safe provider family, without model credentials,
  base URLs, request headers, or arbitrary LiteLLM parameters;
- fallback relationships between model aliases;
- an explicit allowlist of safe router settings, initially
  `routing_strategy`, `cooldown_time`, `allowed_fails`, and
  `num_retries`;
- MCP server aliases and transport kind only, without commands, arguments,
  URLs, headers, or environment values;
- environment-variable reference names and `present: true|false`, never their
  values; and
- validation check identifiers with `pass`, `warn`, or `fail` outcomes.

Unknown fields are omitted rather than passed through.

### Drift projection

The builder compares three allowlisted model identity sets when available:

- deployed LiteLLM configuration aliases;
- gateway model registry aliases; and
- runtime-visible model aliases after removing the public `AI-Gateway:` prefix.

It reports sorted alias-only lists for configured-only, registry-only,
runtime-only, and missing-at-runtime differences. It also reports whether an
explicit registry override exists, but never includes override values.

The endpoint does not infer drift when a required source is unavailable. That
comparison receives `status: unknown` with a typed source error.

## Component Boundaries

### Contract fixtures

The contract defines healthy, degraded, invalid-config, missing-environment,
model-drift, and secret-looking-input fixtures. Contract tests are pure and
validate fixture and documentation invariants without importing runtime code.
The builder child reuses these fixtures in test-first assertions that fail
before its implementation is added.

### Pure snapshot builder

A focused module owns parsing, allowlisting, normalization, redaction, digest
calculation, validation results, and drift comparison. It accepts source data
and timestamps through typed inputs and performs no filesystem, environment,
database, or network access.

The builder is the only component allowed to create `config-snapshot.v1`.
Existing admin-panel helpers may be reused or extracted where their behavior
matches the contract, but the dashboard payload must not be copied wholesale.

### Source adapters

Small adapters gather:

- the deployed LiteLLM configuration from the configured, fixed server-side
  path;
- the model registry through its existing repository abstraction;
- runtime-visible models through the existing bounded LiteLLM client path; and
- environment-reference presence through an injected mapping.

No request field may select a path, host, source, or validation command.
Live-source requests use a five-second total timeout and fail independently.

### FastAPI route

The route owns only feature gating, authentication, exact scope checking,
source orchestration, response-size enforcement, safe audit logging, and HTTP
status mapping. It delegates payload construction to the pure builder.

The implementation must be registered in:

- `docs/openapi/gateway-engine.yaml`;
- `docs/ADMIN_ENDPOINT_EXPOSURE.yaml`; and
- the repository API documentation system described by
  `docs/API_DOCUMENTATION.md`.

## Bounds and Redaction

- Maximum 256 entries per collection.
- Maximum string length 512 characters after normalization.
- Maximum nesting depth 8.
- Maximum serialized response size 64 KiB. A larger result returns a typed
  `502 config_snapshot_too_large` without partial raw content.
- Maximum live-source timeout five seconds, with a two-second connect budget.
- Secret-like keys and values are replaced with `[redacted]` before the
  structural projection is hashed or included in a response. Raw source bytes
  are never hashed for this API, returned, or logged.
- Logs contain operation, outcome, request ID, source identifiers, and counts
  only. They never contain config values, aliases supplied by an untrusted
  request, paths, URLs, prompts, credentials, or raw exceptions.

## Error Model

HTTP-level errors use:

```json
{"error": {"code": "config_snapshot_disabled", "message": "Configuration snapshot is disabled"}}
```

Stable HTTP errors are:

| Condition | Status | Code |
|---|---:|---|
| Feature disabled | 404 | `config_snapshot_disabled` |
| Admin authentication not configured | 503 | `config_snapshot_unavailable` |
| Missing or incorrect admin key | 401 | `config_snapshot_auth_required` |
| Incorrect management scope | 403 | `config_snapshot_scope_forbidden` |
| Serialized response exceeds limit | 502 | `config_snapshot_too_large` |
| Unexpected safe orchestration failure | 503 | `config_snapshot_unavailable` |

Source-level failures in an otherwise valid request remain inside the `200`
snapshot as allowlisted codes such as `source_missing`, `source_invalid`,
`source_timeout`, and `source_unavailable`. No raw exception messages appear.

## Testing Strategy

### Contract child

- Verify exact schema identifier, route, auth and feature-flag matrix.
- Verify fixtures for healthy, degraded, invalid, missing-reference, drift, and
  secret-looking sources.
- Verify non-goals and rollback behavior are documented.

### Builder child

- Begin with failing tests for each fixture.
- Test stable ordering and digest determinism.
- Test allowlist omission for unknown fields.
- Test literal secrets, credential-shaped values, paths, URLs, commands, and
  raw errors never appear.
- Test missing sources produce unknown comparisons rather than false drift.
- Test all collection, depth, and string bounds.

### Adapter child

- Test disabled, missing-auth, wrong-key, wrong-scope, and success behavior.
- Test each source failing independently returns a degraded snapshot.
- Test timeout and response-size handling.
- Test `Cache-Control: no-store` on every response.
- Add in-memory mock integration coverage for the ASGI route and live-source
  adapter.
- Run `make test-fast` before PR creation.

Because the feature touches privileged configuration/auth boundaries, run an
isolated Gate C stack smoke. Verify the default disabled response, enabled
authentication matrix, healthy snapshot, degraded source behavior, and
rollback by disabling the feature. Production enablement is not part of this
epic.

## Delivery and Rollback

Deliver C-SVC-4 as three serialized atomic children:

1. contract and deterministic fixtures;
2. pure snapshot builder; and
3. guarded route and adapters with API documentation.

Each child branches from current `main`, uses its own worktree and dev slot when
needed, passes required CI, merges through a PR, and records Gate D before the
next dependent runtime child proceeds.

The runtime rollback is setting `UNIFIED_CONFIG_ADMIN_API_ENABLED=false`, which
returns the route to its default disabled state without changing any source.
The existing `/admin/status`, dashboard, team/key routes, CLIProxy management
routes, client-config generator, model registry, and GitOps flow remain
unchanged.

## Explicit Non-Goals

- No configuration writes, reloads, restarts, promotion, or rollback actions.
- No generic LiteLLM or CLIProxy proxy endpoint.
- No raw YAML, environment values, command lines, URLs, paths, or credentials.
- No team, key, onboarding, tenant, or RBAC lifecycle changes.
- No policy-profile mutation or legacy `workspace-rules.yaml` enrichment.
- No UI changes.
- No production feature enablement.
