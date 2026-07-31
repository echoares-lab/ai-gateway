# Plan — Cross-Model Tool-Use & Protocol Benchmark

> **Status:** Delivered historical plan (archived 2026-07-31)
> **Implementation evidence:** [PR #440](https://github.com/echoares-lab/ai-gateway/pull/440)
> (model forcing and benchmark harness) and
> [PR #484](https://github.com/echoares-lab/ai-gateway/pull/484)
> (protocol-contract and benchmark integration coverage).
> **Reference correction:** #420 is an unrelated merged CLIProxy pull request,
> not a benchmark epic or atomic issue.

---

## 1. Objectives

1. **Protocol-Level Validation**: Harden the `gateway-engine` protocol translation layers for Claude (Anthropic Messages API) and Cursor (OpenAI hybrid prefixing/caching) with explicit protocol-level contract tests.
2. **Escape Hatch**: Provide a dev-only header override (`X-Force-Model`) to pin the downstream model during evaluation runs and tests, bypassing normal fallback/routing policy.
3. **Tool-Use Fidelity Benchmark**: Automate a test harness that spins up a mock upstream service, routes a headless `claude` CLI client through the gateway-engine to various mock backend families (Anthropic, OpenAI, Gemini), runs benchmark file-edit tasks, and outputs a per-model apply scorecard.

---

## 2. Architecture & Design

```text
                               ┌────────────────────────────────────────────────────────┐
                               │                 claude CLI (Headless)                  │
                               └───────────────────────────┬────────────────────────────┘
                                                           │ (Anthropic Messages API)
                                                           ▼
                               ┌────────────────────────────────────────────────────────┐
                               │                    gateway-engine                      │
                               │  - normalizes protocols                                │
                               │  - intercepts X-Force-Model header                     │
                               └───────────────────────────┬────────────────────────────┘
                                                           │ (OpenAI Chat API)
                                                           ▼
                               ┌────────────────────────────────────────────────────────┐
                               │              Mock Upstream (Python/FastAPI)            │
                               │  - simulates Sonnet, GPT-5, Gemini tool call formats   │
                               └────────────────────────────────────────────────────────┘
```

### 2.1 Model Forcing (`X-Force-Model`)
* When `ALLOW_DEV_MODEL_FORCE=true`, the `gateway-engine` intercepts request headers and rewrites the target `model` to the value of `X-Force-Model`. This allows the benchmark runner to force routing to a specific backend family for mapping evaluation.

### 2.2 Benchmark Harness (`tool_use_bench.py`)
* Automatically starts/stops a lightweight local FastAPI mock upstream server.
* Provisions a temporary workspace / git repository per benchmark task.
* Runs `claude -p "<task prompt>"` (with `ANTHROPIC_BASE_URL` pointing to local gateway-engine).
* Checks the workspace filesystem to verify if the file-edits succeeded byte-for-byte.
* Collects and prints a markdown scorecard matrix of the results.

---

## 3. Delivered implementation areas

The former #421–#423 labels were pull-request numbers for unrelated CLIProxy
work, not benchmark issues. The completed work is recorded by the following
implementation evidence instead.

### Model-forcing escape hatch
- Implement `_maybe_force_model(request, body)` in `services/gateway-engine/api/proxy_routing.py`.
- Call this helper in all 4 main proxy endpoints:
  - `proxy` (catch-all) in `api/proxy_catchall.py`
  - `claude_proxy` in `api/proxy_claude.py`
  - `responses_proxy` in `api/proxy_responses.py`
  - `gemini_proxy` in `api/proxy_gemini.py`
- Add unit test `test_x_force_model_header` in `services/gateway-engine/test_gateway_engine_client_compatibility.py`.
- **Delivered in:** [PR #440](https://github.com/echoares-lab/ai-gateway/pull/440).

### Protocol-level contract tests
- Add a new integration test file `tests/integration/test_protocol_fidelity.py` covering:
  - Cursor User-Agent and `x-gateway-client` header injection.
  - Cursor cache-key isolation by API key hash.
  - Claude system prompt format conversions (string vs content blocks).
  - Claude streaming tool-use response mappings (delta format conversions).
- **Delivered in:** [PR #440](https://github.com/echoares-lab/ai-gateway/pull/440)
  and [PR #484](https://github.com/echoares-lab/ai-gateway/pull/484).

### Cross-model tool-use evaluation harness
- Build mock upstream provider in `scripts/eval/mock_upstream.py` returning realistic tool-use events for Anthropic, OpenAI, and Gemini.
- Build benchmark harness in `scripts/eval/tool_use_bench.py` defining tasks (`single-edit`, `multi-edit-sequence`, etc.) and task verification checkers.
- Wire mock upstream and harness together so a single script runs the full matrix.
- **Delivered in:** [PR #440](https://github.com/echoares-lab/ai-gateway/pull/440)
  and [PR #484](https://github.com/echoares-lab/ai-gateway/pull/484).

---

## 4. Historical test plan

### Gate A (Unit & Lint)
* Run Python linting: `make lint`
* Run gateway-engine unit tests: `PYTHONPATH=services/gateway-engine pytest services/gateway-engine/test_gateway_engine*.py`

### Gate B (Mock Integration)
* Run integration tests: `pytest tests/integration/test_protocol_fidelity.py`
* Run evaluation harness test suite.
