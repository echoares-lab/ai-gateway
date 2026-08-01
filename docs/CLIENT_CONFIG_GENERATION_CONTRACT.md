# Client configuration generation API contract

**Status:** approved contract for C-SVC-2 (#615), contract child #616. This
document and its fixtures define a boundary only; they do not add a route,
execute the shell generator, read secrets, or change production behavior.

## Purpose and rollback

The future `POST /v1/config/generate` endpoint provides deterministic,
copy/paste client profiles equivalent to `scripts/ops/gen-client-config.sh`.
The generator prints placeholders and connection details only. It never calls
the gateway, writes a file, invokes a shell, reads an environment variable, or
looks up a tenant key.

The service is disabled by default with `CONFIG_GENERATION_API_ENABLED=false`.
When disabled, it returns the stable `config_generation_disabled` 404 envelope
without evaluating a request. Operators can immediately use
`gen-client-config.sh` as the rollback path; no migration or persisted state is
required.

## Route and authorization

The implementation child must register this route in
`docs/openapi/gateway-engine.yaml` and `docs/ADMIN_ENDPOINT_EXPOSURE.yaml`:

| Method and route | Required authorization | Effect |
| --- | --- | --- |
| `POST /v1/config/generate` | `x-admin-key` plus `x-management-scope: config:generate` | Generate one or all allowlisted client profiles |

The gateway's client/model bearer key, provider key, edge/WAF header, and a key
embedded in the request body are not management authorization. Missing or
invalid service credentials return the same 401 body; a valid service key with
the wrong scope returns 403. Authorization failures must not disclose request
contents or profile availability.

## Request schema and source precedence

The request is JSON, bounded to 8 KiB, and has no unknown fields:

| Field | Type/default | Constraints |
| --- | --- | --- |
| `client` | string, `all` | one of `cursor`, `claude-code`, `codex`, `gemini`, `openai-sdk`, `all` |
| `base_url` | string, `http://localhost:4000` | absolute `http`/`https` URL, no userinfo/query/fragment, max 512 bytes |
| `key_var` | string, `AI_GATEWAY_KEY` | `^[A-Z_][A-Z0-9_]{0,63}$`; output is a placeholder reference, never a key value |
| `org` | string, `echoares` | safe label, 1–64 chars: `[A-Za-z0-9][A-Za-z0-9._-]*` |
| `workspace` | string, `core` | same safe-label rule |
| `team` | string, `eng` | same safe-label rule |
| `repo` | string, `my-repo` | same safe-label rule |
| `env` | string, `dev` | same safe-label rule |

Source precedence is explicit request value, then a safe service-configured
default (if introduced by a later approved child), then the script defaults in
the table above. Ambient process environment, client headers, gateway keys,
filesystem files, and shell expansion are never sources. Empty strings do not
override a default; malformed values are rejected rather than normalized.

`base_url` is normalized by removing trailing slashes and one trailing `/v1`
segment before profile paths are composed. The value is never allowed to
escape the URL origin through `..`, control characters, a second scheme, or
credentials. The tenant example is derived as
`ak-{org}-{workspace}-{team}-{repo}-{env}` after validation; it is a label,
not a credential.

## Response schema and limits

Successful responses are JSON, bounded to 64 KiB, and deterministic for an
equivalent request. They contain no timestamps, random IDs, or server-local
paths:

```json
{
  "schema_version": "client-config.v1",
  "client": "cursor",
  "base_url": "http://localhost:4000",
  "key_var": "AI_GATEWAY_KEY",
  "tenant_key_example": "ak-echoares-core-eng-my-repo-dev",
  "content_type": "text/plain",
  "config": "# AI Gateway client config ..."
}
```

For `client=all`, `config` is an ordered object keyed by the five profile names
with the same fields and stable order as the shell script (`cursor`,
`claude-code`, `codex`, `gemini`, `openai-sdk`). A profile's text must match the
documented script semantics: base URL `/v1`, `/v1beta`, and Responses API
paths are composed from the normalized base; the `AI-Gateway:` model prefix is
preserved for Cursor; and all key references use `${KEY_VAR}` placeholders.

The implementation may additionally include a bounded request ID, but it must
be derived from a caller-supplied opaque ID or a stable request hash and must
not contain secrets. Responses use `Cache-Control: no-store`.

## Validation and failure matrix

| Condition | Status/code | Required behavior |
| --- | --- | --- |
| Feature flag off | 404 `config_generation_disabled` | no parsing or generation; shell rollback remains available |
| Missing/invalid service key | 401 `config_auth_required` | constant-shape body; no request echo |
| Wrong management scope | 403 `config_scope_forbidden` | do not reveal the required scope |
| Invalid JSON, unknown field, enum, URL, label, or key variable | 400 `invalid_request` | reject before rendering; bounded field location only |
| Request exceeds 8 KiB | 413 `request_too_large` | do not parse or echo the body |
| Rendered response exceeds 64 KiB | 413 `response_too_large` | do not return a partial profile |
| Duplicate idempotency key with same request hash | 200 | return the same bounded deterministic result; render at most once |
| Duplicate key with a different request hash | 409 `idempotency_conflict` | do not reveal either request or prior response |
| Unexpected renderer failure | 500 `config_generation_error` | bounded error class only; no shell/raw exception text |

Errors have exactly `{ "error": { "code": "...", "message": "..." } }`;
messages are fixed English strings and never contain a URL, key, token, path,
request body, or upstream text.

## Redaction and audit requirements

Generated text and audit traces may contain only the client name, normalized
origin/path, safe labels, schema version, bounded duration, outcome, and a
request hash. They must never contain real API keys, bearer values, OAuth or
refresh tokens, cookie values, environment values, credential JSON, absolute
paths, shell arguments, userinfo, or raw exception text. The literal
`${KEY_VAR}` placeholder is safe and is not a credential.

Audit events are bounded and append-only: actor class (not the key), scope,
operation, request ID/hash, profile class (not arbitrary template text),
outcome, reason code, and timestamp. Audit failure must not turn a pure read
into a partial or secret-bearing response.

## Idempotency, compatibility, and rollout

Generation has no external side effects, so equivalent requests are naturally
idempotent. An optional `Idempotency-Key` (1–128 visible ASCII characters) may
be supplied for client retries. If retained by a later implementation, entries
expire after 24 hours and are keyed by a hash of the validated request; a
different request under the same key is a 409. The key itself is never logged.

The shell output remains the compatibility oracle until the implementation
child supplies parity fixtures for every profile, default, URL normalization,
and validation branch. The endpoint must not be enabled in production until
its implementation child passes Gate A/B and any applicable Gate C, then Gate
D verifies the merged commit.

## Child sequencing

1. **#616 (this child):** contract and executable fixtures only.
2. **Implementation child:** pure renderer/adapter, tests, and OpenAPI/exposure
   registration; no secret or shell access.
3. **Follow-up (if needed):** deprecation or client onboarding changes after
   operator review. The existing script remains supported.
