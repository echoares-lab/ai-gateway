# CLIProxy management API contract

**Status:** approved contract for C-SVC-1 (#609), contract child #610. This
document is a design/fixture boundary only. It does not add routes, move OAuth
files, or enable a management service.

## Scope and deployment boundary

The future service wraps the operations currently performed by
`cliproxy-setup.sh` and the CLIProxy management API. It runs on the private
operator network, never on the public client route, and is disabled by default.
The existing shell workflow remains the rollback path until the mutation child
has passed Gate C and operator sign-off.

The service may access only the explicitly mounted CLIProxy state directory
(`~/.cli-proxy-api/`) and a read-only config view. It must not read arbitrary
paths, gateway `.env` files, Docker sockets, OAuth tokens for another tenant,
or provider credentials outside that mount. Read-only operations run as a
dedicated non-root identity with a read-only filesystem and no host network.

## Operations and authorization

The contract is split into scopes so read-only inventory can ship before
mutations:

| Operation (future route) | Scope | Effect |
| --- | --- | --- |
| `GET /health` | `cliproxy:health:read` | bounded liveness/readiness and version; no keys or token paths |
| `GET /v1/management/auth-files` | `cliproxy:sessions:read` | provider/account/status inventory; redact token fields and file contents |
| `GET /v1/management/config` | `cliproxy:config:read` | safe config summary; omit management/API keys, env references, and paths |
| `PATCH /v1/management/auth-files/fields` | `cliproxy:sessions:write` | allowlisted non-secret metadata only; idempotency key required |
| `POST /login/{provider}` | `cliproxy:oauth:write` | starts an operator-approved OAuth flow; never returns a credential |

Routes are illustrative contract names, not implemented endpoints. Every
request requires service authentication and an operator scope; a client API
key, model key, or edge key is not sufficient. Authorization failures return a
stable 401/403 body without revealing whether an account or file exists.

## Decision table and failure behavior

| Condition | Status/result | Safety rule |
| --- | --- | --- |
| Feature disabled/rollback flag off | 404 or `management_disabled` | preserve shell workflow; no upstream call |
| Missing/invalid service credential | 401 | constant-shape response; no secret or account enumeration |
| Valid credential, insufficient scope | 403 | do not disclose required scope or resource existence |
| Malformed JSON/path/provider | 400 | reject before filesystem or CLI access |
| CLIProxy unavailable | 503 | bounded retry budget (none for mutations); no raw upstream body |
| Timeout/cancellation | 504 or cancelled request | terminate child/request, do not retry side effects |
| OAuth/provider failure | 502 with stable provider code | redact callback/error details; leave prior credential untouched |
| Duplicate idempotency key with same request hash | return original bounded result | never run the mutation twice |
| Duplicate key with different request hash | 409 | do not reveal either payload |
| Unexpected exception | 500 `management_error` | audit a bounded error class only; shell rollback remains available |

Read operations have a 5-second timeout, 64 KiB response cap, and at most one
short health retry. Mutations have a 30-second timeout, 256 KiB response cap,
no automatic retry, and a 24-hour idempotency-key retention window. OAuth
callbacks must use an allowlisted loopback/SSH-forwarded origin and an explicit
one-time state value.

## Redaction and audit contract

Responses and traces may include request ID, operation, provider label, account
status, bounded timestamps, duration, outcome, and a hash of the idempotency
key. They must never include API keys, bearer tokens, OAuth authorization codes,
refresh tokens, cookie values, raw callback URLs, prompts, environment values,
credential JSON, arbitrary filesystem paths, or raw CLIProxy error text.

Audit events are append-only and bounded: actor ID, scope, operation, request
ID, resource class (not filename), outcome, reason code, and timestamp. Audit
failure must fail closed for mutations and fail open only for read-only health
metrics; it must not block rollback.

## Rollout and child sequencing

1. **#610 (this contract):** fixtures and tests only; no route or secret access.
2. **Read-only adapter:** health/session inventory with Gate A/B and Gate C if
   compose mounts or real CLIProxy calls change.
3. **Mutation/OAuth adapter:** write scopes, idempotency store, callback
   isolation, deprecation notices, and operator sign-off; Gate C is required.

The `CLIPROXY_MANAGEMENT_API_ENABLED` flag is false by default. Turning it off
must immediately route operators back to `cliproxy-setup.sh`; no database or
credential migration may be required for rollback. Any new public or admin API
route introduced by a later child must be registered in `docs/openapi/`.
