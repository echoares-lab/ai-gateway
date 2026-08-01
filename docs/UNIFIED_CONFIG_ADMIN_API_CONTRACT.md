# Unified Config Admin API Contract

## Purpose and source of truth

This is the executable contract for C-SVC-4's currently implemented read-only
configuration snapshot API. It consumes the approved [Unified Config Admin API
Design](superpowers/specs/2026-08-01-unified-config-admin-api-design.md). Git is
authoritative for structural configuration; the documented runtime model registry
exception is authoritative for explicit model overrides. The pure builder remains
the only component allowed to create `config-snapshot.v1`; the guarded adapter
owns fixed-source acquisition, authentication, and HTTP bounds.

### Global constraints (verbatim)

- Route is exactly `GET /admin/config`; schema is exactly `config-snapshot.v1`.
- `UNIFIED_CONFIG_ADMIN_API_ENABLED=false` is the default and rollback state.
- Enabled requests require `x-admin-key` and exact `x-management-scope: config:read`.
- Missing server auth is `503`; wrong/missing key is `401`; wrong scope is `403`; disabled is `404`.
- Every response, including errors, uses `Cache-Control: no-store`.
- Partial source failures return `200` with `status: degraded` and safe typed errors.
- No request parameter may select a source, file path, host, URL, or command.
- No raw YAML, environment value, secret, credential, URL, filesystem path, command, raw exception, or arbitrary upstream field may be returned or logged.
- Collections are sorted and capped at 256 entries; strings at 512 characters; nesting at depth 8.
- Deployed configuration input is capped at 1 MiB; serialized response is capped at 64 KiB.
- Live-source total timeout is five seconds with a two-second connect budget.
- Only `routing_strategy`, `cooldown_time`, `allowed_fails`, and `num_retries` are exposed from router settings.
- MCP projection contains alias and transport kind only.
- Production enablement, writes, reloads, GitOps promotion, policy mutation, team/key lifecycle, and UI changes are out of scope.
- Any new endpoint must be documented in `docs/openapi/`, `docs/ADMIN_ENDPOINT_EXPOSURE.yaml`, and `docs/API_DOCUMENTATION.md`.

## Route, authentication, and flag matrix

The route is `GET /admin/config`. It is available only with
`UNIFIED_CONFIG_ADMIN_API_ENABLED=true`; its disabled default is
`UNIFIED_CONFIG_ADMIN_API_ENABLED=false`. Disabled requests return before
source inspection. All responses, including errors, use `Cache-Control: no-store`.

| Condition | Status | Code | Behavior |
|---|---:|---|---|
| Feature disabled | 404 | `config_snapshot_disabled` | Do not inspect sources. |
| Admin authentication is not configured | 503 | `config_snapshot_unavailable` | Never accept client or model API keys. |
| `x-admin-key` missing or incorrect | 401 | `config_snapshot_auth_required` | Reject before source inspection. |
| `x-management-scope` is not exactly `config:read` | 403 | `config_snapshot_scope_forbidden` | Reject before source inspection. |
| Any query parameter is supplied | 400 | `config_snapshot_invalid_request` | Fixed server-side sources only; reject before source inspection. |
| Enabled valid `x-admin-key` and `x-management-scope: config:read` | 200 | — | Return bounded snapshot, including degraded data. |
| Serialized response is too large | 502 | `config_snapshot_too_large` | Return no partial raw content. |
| Unexpected safe orchestration failure | 503 | `config_snapshot_unavailable` | Return only typed HTTP error. |

HTTP errors use `{"error":{"code":"config_snapshot_disabled","message":"Configuration snapshot is disabled"}}`.

## `config-snapshot.v1` field table

An authenticated request returns HTTP 200 with schema `config-snapshot.v1`,
including source-degraded snapshots. `generated_at` is supplied by an
injectable UTC clock, excluded from semantic digests, and collections are
deterministically sorted.

| Field | Values | Contract |
|---|---|---|
| `schema` | exactly `config-snapshot.v1` | Versioned identifier. |
| `status` | `ok` or `degraded` | Degraded for non-ok source, validation failure, or non-clean drift. |
| `generated_at` | UTC ISO-8601 | Not in snapshot digest. |
| `sources` | sorted collection | Identifier, kind, `ok`/`missing`/`invalid`/`unavailable`, safe SHA-256 digest, applicable observation time. |
| `models` | object | Allowlisted aliases and safe provider family only. |
| `routing` | object | Allowlisted router values only. |
| `mcp` | collection | Alias and transport kind only. |
| `environment` | collection | Reference name and `present: true|false` only. |
| `validation` | collection | Identifier and `pass`/`warn`/`fail` only. |
| `drift` | object | Alias-only comparison and status. |
| `errors` | bounded collection | Safe typed source errors, never raw exceptions. |

The top-level fields are `schema`, `status`, `generated_at`, `sources`,
`models`, `routing`, `mcp`, `environment`, `validation`, `drift`,
and `errors`.

## Safe projection allowlists

- Models expose aliases, safe provider family, and alias-to-alias fallback
  relationships only; credentials, base URLs, headers, arbitrary parameters,
  raw bytes, paths, hosts, and URLs are forbidden.
- `routing` exposes only `routing_strategy`, `cooldown_time`,
  `allowed_fails`, and `num_retries`; unknown settings are omitted.
- `mcp` exposes alias and transport kind only, never commands, arguments,
  URLs, headers, or environment values.
- `environment` exposes referenced variable names and presence booleans only.
  `validation` exposes identifiers and `pass`, `warn`, or `fail` only.
- Source digests are SHA-256 hashes of canonical sanitized structural
  projections, never raw source bytes. Secret-like keys and values become
  `[redacted]` before inclusion or hashing.

## Source and drift semantics

Sources have stable identifiers such as `litellm-config`, `model-registry`,
and `runtime-visible-models`, and kinds `deployed-file`, `registry`, and
`live-api`. The adapters use fixed server-side sources only.

The builder compares normalized, deduplicated, sorted aliases from deployed
LiteLLM configuration, the gateway registry, and runtime-visible models after
removing the public `AI-Gateway:` prefix. It reports alias-only
`configured_only`, `registry_only`, `runtime_only`, and
`missing_at_runtime` differences and whether an explicit registry override
exists, never override values. If a required source is not `ok`,
`drift.status` is `unknown` with a typed source error; it must not infer
drift. Live sources fail independently under the five-second total and
two-second connect limits.

## Error matrix

| Level | Condition | Code |
|---|---|---|
| HTTP | disabled | `config_snapshot_disabled` |
| HTTP | auth unavailable or safe orchestration failure | `config_snapshot_unavailable` |
| HTTP | missing or incorrect admin key | `config_snapshot_auth_required` |
| HTTP | incorrect management scope | `config_snapshot_scope_forbidden` |
| HTTP | query parameter supplied | `config_snapshot_invalid_request` |
| HTTP | response bound exceeded | `config_snapshot_too_large` |
| Source in HTTP 200 | missing, invalid, timeout, unavailable | `source_missing`, `source_invalid`, `source_timeout`, `source_unavailable` |

Source errors make the snapshot `status: degraded`; raw exception messages
never appear.

## Bounds and redaction

- Collections are sorted and capped at 256 entries, strings at 512 characters,
  and nesting at depth 8.
- Deployed configuration input is capped at 1 MiB before parsing. Serialized
  response is capped at 64 KiB; overflow returns `502 config_snapshot_too_large`
  with no partial raw content.
- Raw YAML, environment values, secrets, credentials, URLs, filesystem paths,
  commands, raw exceptions, and arbitrary upstream fields are never returned,
  logged, or hashed.
- Logs contain only operation, outcome, request ID, source identifiers, and
  counts; never configuration values, untrusted aliases, paths, URLs, prompts,
  credentials, or raw exceptions.

## Fixtures

`services/gateway-engine/test_gateway_engine_unified_config_contract.py`
provides deterministic, runtime-free fixture constants:

| Fixture | Scenario |
|---|---|
| `HEALTHY_INPUT` | Matching `gpt-safe` configured, registry, and runtime aliases with safe routing. |
| `DEGRADED_INPUT` | Runtime aliases absent with `source_timeout`. |
| `INVALID_CONFIG_INPUT` | Malformed LiteLLM YAML. |
| `MISSING_ENV_INPUT` | Referenced `OPENAI_API_KEY` is not present. |
| `MODEL_DRIFT_INPUT` | Registry also contains `claude-safe`. |
| `SECRET_LOOKING_INPUT` | Secret-looking key and URL that must never leak. |

These are test-only input values, not runtime configuration or credentials.

## Non-goals

No configuration writes, reloads, restarts, promotion, or rollback actions; no
generic LiteLLM or CLIProxy proxy; no raw YAML, values, commands, URLs, paths,
or credentials; no team/key, onboarding, tenant, RBAC, or policy-profile
lifecycle changes; no UI change; and no production enablement.

## Rollback

Set `UNIFIED_CONFIG_ADMIN_API_ENABLED=false`. This restores the default typed
404 without changing any source. Existing `/admin/status`, dashboard,
team/key routes, CLIProxy management routes, client-config generator, model
registry, and GitOps flow remain unchanged.

## Serialized dependencies

1. Task 1 / #635 delivered this contract and deterministic fixtures.
2. Task 2 / #636 delivered the pure snapshot builder consuming them.
3. Task 3 / #637 implements the guarded adapters and `GET /admin/config`,
   including OpenAPI and exposure registration.

The endpoint is registered in `docs/openapi/gateway-engine.yaml`,
`docs/ADMIN_ENDPOINT_EXPOSURE.yaml`, and `docs/API_DOCUMENTATION.md`.
