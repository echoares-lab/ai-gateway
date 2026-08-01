# MCP visibility and local tool-hosting contract

**Status:** approved implementation contract for C-RT-4 (#601), contract child
#602. This document defines the seam and the observable behaviour that the
serialized implementation children must satisfy. It does not enable MCP
filtering or start a local tool host.

## Scope and compatibility

The contract applies to every HTTP adapter that can carry a tool-bearing
request:

| Adapter | Public route | Canonical policy seam |
| --- | --- | --- |
| OpenAI chat/catch-all | `POST /v1/chat/completions` (and other POST catch-all routes) | `PolicyHookBoundary.apply` |
| OpenAI Responses (Codex) | `POST /v1/responses` | `PolicyHookBoundary.apply` |
| Anthropic Messages (Claude) | `POST /v1/messages` | `PolicyHookBoundary.apply` |
| Gemini CLI | `POST /v1beta/models/{model}:generateContent` and `:streamGenerateContent` | `PolicyHookBoundary.apply` |

Adapters normalize their native wire format first, then invoke the same
boundary before forwarding to LiteLLM. WebSocket frame translation and
provider-specific MCP rewrites are outside this contract. A request with no
MCP policy remains backward compatible: ordinary tools are passed through and
the implementation must not invent a visibility restriction.

The policy hook is optional and disabled by default. Any implementation child
must retain the existing fail-open rollback: if policy is disabled or cannot
produce a valid decision, forward the original normalized request unchanged.

## Visibility vocabulary

An MCP alias is the stable name from the LiteLLM `mcp_servers` registry (for
example, `mcp-fetch`). A tool is considered MCP-originated only when the
registry/materializer proves its alias; an unrecognised tool is treated as an
ordinary client tool and is never guessed to be MCP from its name or
description.

The effective policy is the most-specific non-empty `policy_json.mcp` section
in the existing org → workspace → team → repo chain. `allowed_mcp_servers =
null` means no visibility filter (the compatibility default); a list is an
allowlist. `denied_mcp_servers` is retained when a denylist cannot be resolved
against the registry so that a later materializer can enforce it.

### Decision table

| Condition | Visibility result | Request result | Trace/metadata rule |
| --- | --- | --- | --- |
| Policy disabled | No filter | Forward unchanged | Do not add policy or MCP fields |
| No evaluator configured | No filter | Forward unchanged | Record only a bounded `policy_unavailable` counter/trace if available |
| Evaluator timeout/error/malformed decision | No filter (fail-open) | Forward unchanged | Never include exception text, prompts, credentials, tenancy IDs, or raw decision |
| No MCP section | No filter | Forward unchanged | Preserve ordinary tool definitions |
| `allowlist` with known aliases | Expose only listed, registry-known aliases | Denied MCP tools are omitted; an invocation of a denied alias is rejected with the adapter's stable policy-denied response | Propagate only bounded alias metadata; no tool schema or arguments |
| `allowlist` with unknown aliases | Unknown aliases expose nothing | Do not fail the whole request; no unknown MCP tool is materialized | Count unknown aliases using a bounded count, not raw names |
| `denylist` with known aliases | Hide listed aliases; expose other registry-known aliases | Denied MCP tools are omitted; a denied invocation is rejected with the stable policy-denied response | Same bounded metadata rule |
| `denylist` with unknown aliases or no registry | Preserve the deny list for the materializer; never claim an alias is visible | Forward ordinary tools; deny only when the materializer proves an MCP alias is denied | Do not log raw unknown aliases |
| Empty denylist / empty policy | No filter | Forward unchanged | No empty policy fields are injected |

The implementation must make filtering idempotent. Reapplying the hook cannot
restore a denied tool, duplicate metadata, or mutate a non-MCP tool. A policy
decision is not a substitute for authentication or tenancy isolation; those
remain the responsibility of the existing layers.

## Metadata, redaction, and bounds

The request metadata sent to LiteLLM may carry only the following MCP fields:

- `allowed_mcp_servers`: a de-duplicated list of registry aliases, capped at
  128 entries and 128 UTF-8 bytes per alias;
- `denied_mcp_servers`: the same bounded alias shape; and
- `mcp_visibility_mode` (`allowlist`, `denylist`, or `unfiltered`).

No MCP tool description, function schema, arguments, prompt text, bearer/API
key, credential identifier, tenancy key, filesystem path, evaluator exception,
or arbitrary policy field may be copied into metadata or operator traces.
Trace payloads are bounded to 32 aliases (and 128 bytes per alias), plus
boolean/count fields such as `mcp_filtered`, `mcp_unknown_count`, and
`mcp_denied_count`. Redaction is applied before logging or returning a policy
debug response; unknown fields are dropped, not recursively serialized.

## Local tool-host boundary (follow-up child)

The local host is a separate, opt-in adapter and is not implemented by #602.
Its contract is:

1. Run with a dedicated non-root identity, a read-only filesystem, no host
   network by default, and an explicit per-tool working directory. It may not
   read gateway configuration, OAuth volumes, environment secrets, or another
   tenant's workspace.
2. Accept only a validated alias plus JSON arguments. Request and response
   bodies are each capped at 1 MiB; nesting is capped at 32 levels; a single
   tool call has a 10-second wall-clock timeout and a 32 MiB output buffer.
   Exceeding a bound returns a stable, non-sensitive error and terminates the
   call.
3. Propagate cancellation and never retry a side-effecting call implicitly.
   The host must not execute an alias absent from the effective visibility
   decision, even if the caller supplies a tool definition.
4. Emit only request ID, bounded alias, duration, outcome, and size counters.
   Rollback is an environment flag/route disable that immediately bypasses the
   host and returns to the existing upstream path; no database migration is
   required.

The local host child must add isolation tests (including credential and
cross-workspace read attempts), timeout/size-limit tests, and a Gate C review
before any production flag is enabled.

## Child sequencing and acceptance

Children are serialized under #601:

1. **#602 (this contract):** fixtures and seam tests only; no runtime change.
2. **HTTP visibility implementation:** enforce the decision table on the four
   adapters, add redacted traces, and run Gate A/B plus Gate D.
3. **Isolated local host and rollout:** implement the boundary above, run Gate
   C, obtain operator sign-off, then consider enabling the flag.

Each child must keep the feature flag off until its tests and rollback path are
verified. Any new API route introduced by a child must also be registered in
`docs/openapi/` per repository policy.
