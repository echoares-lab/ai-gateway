# Codex WebSocket frame translation contract

**Status:** approved contract for C-RT-5 (#621), contract child #622. This is
a design and fixture boundary only. It does not alter `ws_router.py`, enable a
feature flag, or connect to a provider.

## Purpose and rollback

Codex opens `WS /v1/responses` for persistent multi-turn sessions. Today the
gateway proxies frames directly to CLIProxy. Option B introduces an opt-in
translation boundary that maps a versioned, provider-independent frame stream
to the existing Responses/Chat Completions routing semantics.

`CODEX_WS_TRANSLATION_ENABLED=false` is the default. When false, the existing
direct CLIProxy WebSocket proxy, authentication normalization, credential
selection, and current policy bypass behavior are unchanged. Disabling the
flag must immediately roll back to that path without persisted state or a
connection migration.

## Handshake, authorization, and negotiation

The public route remains `WS /v1/responses`. The client may authenticate with
the existing `Authorization: Bearer`, `api-key`, or `?key=` forms; the gateway
normalizes them exactly as the current router does. Client/model credentials
are never logged or accepted as an operator credential. The upstream
CLIProxy-specific management key is server-side only.

The translator advertises subprotocol `codex-ws.v1`. A client that does not
negotiate this subprotocol uses the existing direct proxy path while the flag
is enabled, preserving older Codex versions. Handshake failures are constant
shape: close `1008` (`policy_violation`) with the safe reason `authentication
required`; no account or model existence is disclosed.

## Frame schema

Frames are UTF-8 JSON objects. Binary frames are accepted only when their bytes
are valid UTF-8 JSON and otherwise close with `1003` (`unsupported_data`). Every
frame is at most 64 KiB encoded and has a `type`, `request_id`, and (except
`request.start`) a monotonically increasing `sequence`.

| Type | Required fields | Meaning |
| --- | --- | --- |
| `request.start` | `request_id`, `model`, `input` | Begin one Responses request; `input` is bounded JSON and is never echoed in logs |
| `request.delta` | `request_id`, `sequence`, `delta` | Optional client-side continuation/input delta |
| `request.cancel` | `request_id`, `sequence` | Idempotently cancel the request; reason is bounded and non-secret |
| `response.delta` | `request_id`, `sequence`, `delta` | Provider-independent text/reasoning delta |
| `response.tool_call` | `request_id`, `sequence`, `name`, `arguments` | Bounded tool call with opaque call ID |
| `response.completed` | `request_id`, `sequence`, `usage` | Terminal success with bounded token usage counters |
| `response.error` | `request_id`, `sequence`, `code`, `message` | Terminal safe error; no upstream text or credentials |

`request_id` is 1–128 visible ASCII characters matching
`[A-Za-z0-9._:-]+`. `sequence` starts at zero for each request and increases by
one; duplicate frames are ignored only when their complete hash matches the
already-accepted frame. A duplicate with different content is a protocol
error. `delta` and tool arguments are each bounded to 32 KiB and usage values
are non-negative integers below 2^53.

The translator emits one terminal frame (`response.completed`, `response.error`,
or cancellation) for each accepted request. No frame is emitted after
terminal state. A connection may carry at most 16 in-flight request IDs and an
output queue of 128 frames; excess work receives `rate_limited` and does not
grow memory without bound.

## State, cancellation, and timeouts

Each request follows `idle → requesting → streaming → terminal`. Cancellation
may occur in `requesting` or `streaming` and moves to `cancelled`; repeated
`request.cancel` is a no-op that returns the same terminal cancellation result.
Late provider frames after cancellation or terminal state are dropped and are
never forwarded to another request. Disconnects cancel all active requests and
release routing/credential state.

The first frame and every subsequent frame have a 64 KiB limit. Translation
has a 30-second request deadline, a 5-second handshake deadline, and a 120
second idle connection timeout. Backpressure pauses upstream reads when the
bounded output queue is full; it never spawns unbounded tasks. A timeout emits
`response.error` code `timeout` once and closes normally (`1000`) after queued
terminal data drains.

## Provider-independent mapping and policy boundary

`request.start.model` and normalized input are passed through the same model
resolution and policy context as HTTP Responses requests. Provider-specific
wire fields are translated into the seven frame types above; unknown fields are
ignored rather than reflected. Tool calls preserve an opaque call ID and
bounded JSON arguments but never include provider credentials.

Policy evaluation is opt-in according to the existing WS policy flags. A
denial emits `response.error` code `policy_denied` and closes with `1008`. A
policy timeout, malformed decision, or evaluator exception follows the current
bounded fail-open rollback to direct proxy unless strict WS policy is enabled;
the decision and reason are recorded only as safe codes. Credential routing
metadata is internal and must not be placed in client frames.

## Failure and close matrix

| Condition | Frame/close | Safety rule |
| --- | --- | --- |
| Translation flag off | direct proxy | no frame parsing or translation state |
| Missing/invalid client auth | close `1008`, `authentication required` | constant shape; no account enumeration |
| Malformed JSON/schema/sequence | `response.error` `protocol_error`, close `1003` | bounded reason only |
| Frame over 64 KiB | close `1009`, `message_too_large` | do not echo bytes |
| In-flight or queue limit | `response.error` `rate_limited` | preserve existing requests; no unbounded buffering |
| Provider timeout | `response.error` `timeout`, close `1000` | cancel upstream work; no retry of side effects |
| Provider/auth failure | `response.error` `upstream_unavailable` | redact status/body and preserve prior state |
| Policy denial | `response.error` `policy_denied`, close `1008` | never forward a denied request |
| Client disconnect | cancel active IDs, close `1000` | release state and ignore late frames |
| Unexpected exception | `response.error` `translation_error`, close `1011` | log only exception class and request hash |

Error messages are fixed safe strings. They never contain prompts, frame input,
authorization values, callback URLs, filesystem paths, provider bodies, or raw
exception text.

## Observability, versioning, and rollout

Safe metrics/audit fields are limited to protocol version, request ID hash,
model family (not the raw prompt), frame type, sequence, bounded duration,
queue depth, outcome code, and close code. Logs must use the existing safe
header mapping and never include bearer/API keys, tool arguments, prompts, or
provider responses.

The contract version is `codex-ws.v1`; additive optional fields require a new
fixture and must not change sequence or terminal semantics. Breaking changes
negotiate a new subprotocol and retain direct-proxy fallback for old clients.
The implementation child must add OpenAPI/operational exposure documentation
for any new HTTP control route, keep the translation flag off in production,
and pass Gate A/B plus Gate C real WebSocket smoke before operator sign-off.
