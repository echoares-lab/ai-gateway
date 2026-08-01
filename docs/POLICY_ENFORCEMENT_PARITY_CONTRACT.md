# C-RT-3 strict policy and WebSocket parity contract

This is the executable contract for C-RT-3 implementation children. It
supersedes ambiguity in the older policy design notes while preserving the
current default behavior: HTTP policy remains fail-open and Codex WebSocket
evaluation remains opt-in. This child changes no production behavior.

## Boundary and ownership

All protocol adapters consume the `PolicyHookBoundary` introduced by C-AUD-8
(`services/gateway-engine/api/policy_hooks.py`). The following call sites are
owned by the serialized implementation children:

| Child | Hotspots | Responsibility |
| --- | --- | --- |
| #592 (this contract) | `docs/`, policy/router tests, mock fixtures | Define outcomes, metadata, traces, timing, and rollback. |
| #593 (next; HTTP enforcement) | `api/proxy_catchall.py`, `proxy_responses.py`, `proxy_claude.py`, `proxy_gemini.py`, `api/policy_hooks.py` | Enforce strict HTTP decisions behind the existing seam. |
| #594 (after #593; WS parity) | `api/ws_router.py`, `main.py`, WS tests | Implement opt-in first-frame/model-aware parity and preserve bypass fallback. |

Only one child may edit the shared request-path hotspots at a time. #593 must
merge and pass Gate D before #594 is claimable.

## HTTP decision matrix

The internal normalized request body is evaluated after protocol conversion and
tenancy extraction. A decision is attached only as
`metadata.routing_decision`; existing caller metadata is preserved.

| Condition | Required action in #593 | Upstream call | Trace/admin fields |
| --- | --- | --- | --- |
| Policy disabled | Forward unchanged; do not evaluate. | Yes | No decision; no policy error. |
| Evaluator available, `gate=allow` | Forward with the complete routing decision metadata. | Yes | `gate=allow`, policy version, bounded rules. |
| Evaluator available, `gate=deny` | Return a stable typed policy denial (HTTP 403) with no upstream call. | No | Record deny decision; never expose request/auth secrets. |
| Evaluator unavailable | Fail open and forward unchanged. | Yes | Record `evaluator unavailable`; no routing metadata. |
| Evaluator timeout | Fail open and forward unchanged within the configured budget. | Yes | Record bounded timeout classification; no stack/secret details. |
| Evaluator exception | Fail open and forward unchanged. | Yes | Record `evaluate error`; redact and bound the message. |
| Malformed/unknown decision | Treat as evaluator failure and fail open. | Yes | Record `malformed decision`; never partially apply metadata. |

The matrix applies identically to chat completions, Responses, Claude
Messages, and Gemini generate/stream routes. Response conversion and upstream
authorization ordering remain unchanged.

## WebSocket parity matrix

Codex `WS /v1/responses` currently accepts the client, authenticates, and then
proxies frames directly to CLIProxy. The following behavior is the contract for
#594:

| Flags/state | Upgrade behavior | First-frame/model behavior | Failure behavior |
| --- | --- | --- | --- |
| `POLICY_ENGINE_ENABLED=false` | Default bypass. | Do not evaluate. | Proxy normally. |
| `POLICY_ENGINE_ENABLED=true`, `POLICY_ENGINE_WS_EVALUATE=false` | Default bypass remains active. | Do not evaluate. | Proxy normally. |
| Both flags true; model known at upgrade | Evaluate once through `PolicyHookBoundary`. | Apply only safe routing headers (`X-Session-ID`, quota/deprioritization hints). | Timeout/error/malformed decision fails open to direct proxy. |
| Both flags true; model only in first frame | Accept upgrade, evaluate once after bounded first-frame parse. | Never buffer or replay more than the bounded first frame; preserve frame order. | Parse/evaluate failure rolls back to direct proxy. |
| Opt-in decision `gate=deny` | Close before upstream connect (code 1008, bounded reason). | No client secret in close reason or logs. | No upstream connection. |

The opt-in evaluation budget is 100 ms by default and must not block frame
forwarding indefinitely. Handshake headers are always filtered through the
existing credential redaction/stripping rules.

## Trace, redaction, and rollback invariants

* Trace entries contain `evaluated_at`, bounded `evaluate_ms`, decision gate,
  policy version/rules, and a normalized error class (`unavailable`,
  `timeout`, `error`, or `malformed`).
* Admin decision samples allow only `gate`, `rules_applied`, `policy_version`,
  `quota_aware_mode`, bounded credential IDs, and redacted `session_key`.
  Tenancy, authorization, prompts, frame contents, and arbitrary evaluator keys
  are excluded.
* Any enforcement implementation can be rolled back by disabling the policy
  flag; disabled mode is the static forwarding path and must not evaluate.
* A failed opt-in WebSocket evaluation rolls back to direct CLIProxy proxying;
  only an explicit deny prevents the upstream connection.

The contract matrix is captured by
`services/gateway-engine/test_gateway_engine_policy_enforcement_contract.py`.
