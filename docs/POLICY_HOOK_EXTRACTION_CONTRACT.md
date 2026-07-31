# C-AUD-8 policy-hook extraction contract

This document is the executable boundary for the follow-up C-AUD-8
implementation child. It inventories the policy hooks currently used by the
request path and records behavior that must remain unchanged while those hooks
are moved behind an injectable seam.

## Current call-site inventory

| Call site | Protocol/path | Current hook | Contract notes |
| --- | --- | --- | --- |
| `api/proxy_catchall.py::proxy` | OpenAI-compatible catch-all, including chat completions and compact responses | `_extract_and_apply_tenancy`, `_apply_policy_engine`, `_maybe_force_model` | POST body is mutated only by the existing tenancy/policy/forced-model sequence; exceptions fail open. |
| `api/proxy_responses.py::responses_proxy` | `POST /v1/responses` | `_extract_and_apply_tenancy`, `_apply_policy_engine`, `_maybe_force_model` | Responses input is converted to the internal chat shape before policy evaluation. |
| `api/proxy_claude.py::claude_proxy` | `POST /v1/messages` | `_extract_and_apply_tenancy`, `_apply_policy_engine`, `_maybe_force_model` | Claude Messages is converted before policy evaluation; the public Claude response shape is unchanged. |
| `api/proxy_gemini.py::gemini_proxy` | Gemini generate/stream routes | `_extract_and_apply_tenancy`, `_apply_policy_engine`, `_maybe_force_model` | Gemini input is converted before policy evaluation; query/header auth is normalized first. |
| `api/ws_router.py::responses_websocket` | Codex `WebSocket /v1/responses` | `codex_ws_policy_bypass`, `build_routing_context`, `evaluate_policy_engine` | Policy evaluation is bypassed by default. It is enabled only when both `POLICY_ENGINE_ENABLED` and `POLICY_ENGINE_WS_EVALUATE` are true. Denials close with code 1008 before upstream connect. |
| `main.py::configure_proxy_routes/create_ws_router` | Dependency wiring | `ProxyRouterDeps`, `WsRouterDeps` | The implementation child must preserve these injection points and keep `main.py` as wiring only. |

## Target injectable seam

The implementation child may extract the following interface, but must not
change its semantics:

```text
PolicyHooks
  enabled() -> bool
  build_context(token, normalized_body, budget?) -> RoutingContext
  evaluate(context) -> RoutingDecision | None
  apply(token, normalized_body) -> normalized_body
  record_trace(decision, elapsed_ms, error?) -> None
  redact_decision(decision) -> admin-safe mapping
```

HTTP protocol adapters call `apply` after converting to the internal body and
before upstream authorization normalization/forwarding. The WebSocket adapter
uses `enabled()` plus its explicit opt-in flag, then calls `build_context` and
`evaluate` only when opt-in is active.

## Invariants locked by the contract tests

* Disabled policy returns the same request body and does not evaluate.
* Missing evaluator, evaluator exceptions, and timeout exceptions fail open:
  the request continues without `metadata.routing_decision`; a trace records
  the unavailable/error outcome when admin tracing is enabled.
* A successful decision is attached only at `body.metadata.routing_decision`.
  Existing caller metadata is preserved.
* Admin decision samples expose only `gate`, `rules_applied`,
  `policy_version`, and the bounded routing fields (`quota_aware_mode`, a list
  of credential IDs, and a redacted `session_key`). Context, tenancy tokens,
  arbitrary decision keys, and error details are never exposed in the sample.
* HTTP protocol paths listed above all use the shared apply hook.
* Codex WebSocket policy is bypassed for every flag combination except both
  feature flags enabled; an opted-in denial closes before connecting upstream.

No production behavior or public API surface is introduced by this contract
child. The follow-up implementation child must migrate the listed call sites
atomically and retain the tests in
`test_gateway_engine_policy_hook_contract.py`.
