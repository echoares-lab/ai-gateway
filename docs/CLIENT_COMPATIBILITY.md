# Client Compatibility Matrix & Integration Profiles

> **Status:** Approved. Foundational model for [Roadmap Epic #36 — First-class client compatibility and integration profiles](https://github.com/echoares-lab/ai-gateway/issues/36).
> This document specifies the client compatibility matrix, defines named integration profiles, maps client protocols to translator code paths, and analyzes integration test coverage gaps.

---

## 1. Supported Client Matrix

The AI Gateway acts as a protocol translation proxy sitting in front of LiteLLM. Below is the support matrix mapping key developer client applications to their target protocol endpoints and support levels:

| Client App | Protocol / Target Endpoint | Support Level | Implementation Status & Caveats |
|---|---|---|---|
| **Cursor** | `/v1/chat/completions`, `/v1/models` | **Full** | Translates Cursor/OpenAI hybrid schema to standard chat completions. Employs `AI-Gateway:` prefix to prevent local model metadata collision. |
| **Claude Code** | `/v1/messages` | **Full** | Translates Anthropic Messages payload format to OpenAI Chat Completions. Supports tool use, streaming (SSE), and headers/metadata extraction. |
| **Codex CLI** | `/v1/responses`, `/v1/responses/compact` | **Full** | Supports OpenAI Responses API body format. Compaction requests on non-OpenAI models are dynamically emulated by rewriting the target to `gpt-5-5`. |
| **Gemini CLI** | `/v1beta/models/*` | **Full** | Maps Google Gemini schema format (contents, parts) to OpenAI Chat Completions. Supports function calling, streaming, and metadata. |
| **Generic OpenAI SDK** | `/v1/chat/completions` | **Passthrough** | Standard OpenAI-compliant HTTP payload mapped directly to LiteLLM's corresponding endpoint. |
| **MCP-Native Clients** | Stdio / SSE MCP endpoints | **Full** | LiteLLM acts as the central control plane, hosting hosted fastmcp and stdio servers for local tool invocation. |

---

## 2. Integration Profiles

An **Integration Profile** defines the exact base URL, authorization mapping, model prefixing rules, and telemetry tags applied when a client interacts with the gateway.

### 2.1 Profile Definitions

#### Cursor Profile
- **Base URL:** `http://localhost:4000/v1` (forwarded via translator)
- **Authorization:** `Bearer ak-{org}-{workspace}-{team}-{repo}-{environment}`
- **Model Prefixing:** Uses `AI-Gateway:` prefix in `/v1/models` so Cursor distinguishes gateway-managed LLMs from local or defaults. The prefix is dynamically stripped by `_strip_prefix` in `translator.py` before forwarding to LiteLLM.
- **Cache Strategy:** Keyed by client `Authorization` token hash to ensure cross-user isolation.

#### Claude Code Profile
- **Base URL:** `http://localhost:4000/v1`
- **Authorization:** Passed in `x-api-key` header (mapped to `Authorization: Bearer ak-...` by translator).
- **Schema Mapping:** Map messages roles (`user`, `assistant`), type conversions, and convert Anthropic tool definitions (`tool_use`) to OpenAI tools format.

#### Codex Profile
- **Base URL:** `http://localhost:4000/v1/responses`
- **Authorization:** `Bearer ak-...`
- **Responses Compaction:** Calls to `/v1/responses/compact` with non-OpenAI models are rewritten to `gpt-5-5` to avoid upstream proxy unsupported failures.
- **WebSocket multi-turn:** Codex CLI opens `WS /v1/responses` for persistent sessions. The translator proxies directly to CLIProxy (`CLIPROXY_WS_URL`), bypassing LiteLLM and the policy-engine evaluate path. See [POLICY_ENGINE_AND_ROUTING_REFACTOR.md §9](./POLICY_ENGINE_AND_ROUTING_REFACTOR.md#9-websocket-path--codex-bypass-issue-38-14). CLIProxy session-affinity and credential routing still apply upstream.

#### Gemini Profile
- **Base URL:** `http://localhost:4000/v1beta/models/...`
- **Authorization:** Passed in `?key=` query param, `x-goog-api-key` header, or standard bearer token (normalized to Bearer auth).

---

## 3. Translator Path Mapping

The entrypoints in `services/translator/translator.py` process requests according to their respective profiles:

```text
Incoming HTTP Request
  │
  ├─── /v1beta/models/{model_action:path} ──> gemini_proxy()
  ├─── /v1/responses                      ──> responses_proxy() or responses_websocket()
  ├─── /v1/messages                       ──> claude_proxy()
  └─── /{path:path}                       ──> proxy() [Catch-all / Cursor / OpenAI]
```

---

## 4. Contract-Test Gap Analysis

An analysis of `tests/integration/test_gateway.py` against the supported client matrix reveals the following test coverage gaps:

### 4.1 Identified Gaps

1. **Claude Code Tool-calling & Streaming:**
   - **Status:** Basic message mapping is tested.
   - **Gaps:** Missing integration tests for streaming SSE outputs containing Anthropic tool calling blocks (`content_block_start`, `content_block_delta` containing `input_json_delta` fields).
2. **Gemini CLI Function Calling:**
   - **Status:** Basic text completion mapping is tested.
   - **Gaps:** Missing contract tests for Gemini function call mappings (`functionCall` payload blocks) and function response injections (`functionResponse`).
3. **Responses API Compaction Interception:**
   - **Status:** Unit tests exist for translator hook level.
   - **Gaps:** Missing E2E integration test hitting `/v1/responses/compact` with a Claude model mapping to verify full client-gateway lifecycle works on production slots.
4. **WebSocket Protocol Multi-turn Compatibility:**
   - **Status:** E2E websocket proxy is tested for raw connection establishment.
   - **Policy engine:** WS path explicitly bypasses policy-engine evaluate (issue 38-14). HTTP `/v1/responses` uses LiteLLM + optional evaluate when `POLICY_ENGINE_ENABLED=true`.
   - **Gaps:** Missing multi-turn conversation and cancellation frame integration tests.

---

## 5. Proposed Child Issues (Epic #36)

To close the identified contract-test gaps and finalize client compatibility:

1. **#80 — test(compat): implement Claude Code tool-calling and streaming integration tests**
   Write integration tests simulating Claude Code clients performing complex tool executions with streaming output checks.
2. **#81 — test(compat): implement Gemini CLI function-calling contract tests**
   Expand integration tests to verify Gemini-format function call and response payload translation.
3. **#82 — test(compat): add Responses API compaction integration test**
   Add a gateway test verifying that calling the compaction endpoint with a non-OpenAI model successfully maps, resolves, and returns a valid compaction block.

---

## 6. References
- [Tenancy & Workspace Domain Model](./TENANCY.md)
- [Roadmap Status](./ROADMAP.md)
- [Architecture Decision Record — MCP Control Plane](./ARCHITECTURE.md)
- [Repo Improvement Workflow](../REPO_IMPROVEMENT_WORKFLOW.md)
