# Feature Candidates (Not Yet Approved)

Inventory of product and platform ideas that are **not** approved for the
active roadmap. Agents must **not** claim or implement work from this file.

Promotion path:

1. Explicitly move the item into [ROADMAP.md](./ROADMAP.md) under Now / Next /
   Parked as appropriate.
2. Open atomic GitHub child issues with acceptance criteria and
   `status:ready` / `status:approved`.
3. Only then may agents claim those issues under `docs/process/REPO_IMPROVEMENT_WORKFLOW.md`.

Scoring keys:

| Field | Scale |
|-------|--------|
| Effort | S (days) / M (1–2 weeks) / L (multi-week / multi-epic) |
| Risk | L / M / H (ops, contract, or blast-radius) |
| Need/fit | high / med / low / unclear — relative to current direction |
| Status | `candidate` until promoted |

Last reviewed: 2026-07-17.

## Promoted / done

These entries are retained only as promotion history and are not unapproved
inventory.

| ID | Summary | Destination | Status |
|----|---------|-------------|--------|
| C-OPS-1 | CLIProxy upstream-patch migration and third-party dependency update/test/rollback loop | Roadmap epic [#413](https://github.com/echoares-lab/ai-gateway/issues/413) and atomic children #414–#419 plus CLIProxyAPI #11–#13 | promoted |

---

## Ops and credential intelligence (beyond thin wave)

Thin approved work (quota unit tests / small polish) lives on the roadmap.
Everything below stays candidate until promoted.

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-CRED-1 | Credential pool orchestration: inventory, health state machine, quarantine/cooldown, alerts | L | H | med | Closed epic [#33](https://github.com/echoares-lab/ai-gateway/issues/33); [CREDENTIAL_HEALTH.md](./CREDENTIAL_HEALTH.md) | candidate |
| C-CRED-2 | Multi-account load balancing / remapping across OAuth credentials | L | H | med | Builds on C-CRED-1; CLIProxy management APIs | candidate |
| C-CRED-3 | Operator remediation workflows (API/UI) for expired, rate-limited, or degraded credentials | M | M | med | Admin console + C-CRED-1 | candidate |
| C-CRED-4 | Chargeback / budget attribution hooks from credential and tenant usage | L | H | unclear | [CHARGEBACK_ATTRIBUTION.md](./CHARGEBACK_ATTRIBUTION.md); tenancy decision | candidate |

---

## Tenancy and adoption

Parked on the roadmap as coordination anchors; expanded scope remains candidate
until a multi-tenant decision is made.

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-TEN-1 | Full multi-tenant workspace lifecycle (org/workspace/team/repo) | L | H | unclear | [#30](https://github.com/echoares-lab/ai-gateway/issues/30); [TENANCY.md](./TENANCY.md) | candidate |
| C-TEN-2 | Self-service onboarding for repos, apps, and AI clients | L | M | unclear | [#34](https://github.com/echoares-lab/ai-gateway/issues/34); depends on C-TEN-1 | candidate |
| C-TEN-3 | Admin tenant/team panel (usage, quota, credential health per tenant) | M | M | unclear | [#109](https://github.com/echoares-lab/ai-gateway/issues/109); depends on C-TEN-1 | candidate |
| C-TEN-4 | RBAC and identity integration | L | H | unclear | Tenancy + admin/control-plane contracts | candidate |

---

## Model lifecycle and config promotion

Cheap-drift check and `/model/new` / `/model/delete` hot-add shipped on `main`
(2026-07). Further automation is candidate.

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-MDL-1 | Full discovery orchestration (probe → registry → LiteLLM reconcile loops) | L | M | med | Prior epic [#230](https://github.com/echoares-lab/ai-gateway/issues/230); [MODEL_MANAGEMENT_RESEARCH.md](./MODEL_MANAGEMENT_RESEARCH.md) | candidate |
| C-MDL-2 | Staging / config release channels for model and tool changes | L | H | med | Closed epic [#35](https://github.com/echoares-lab/ai-gateway/issues/35); [CONFIG_PROMOTION.md](./CONFIG_PROMOTION.md); [CICD_PHASE2_STAGING.md](./CICD_PHASE2_STAGING.md) | candidate |
| C-MDL-3 | External model metadata expansion in `config/model-registry.yaml` | M | M | low | [UNMERGED_FEATURES.md](./UNMERGED_FEATURES.md) | candidate |

---

## Routing, policy, and tools

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-RT-1 | Adaptive routing runtime (health/latency/429-driven fallback) | L | H | med | Closed design [#31](https://github.com/echoares-lab/ai-gateway/issues/31); [ADAPTIVE_ROUTING.md](./ADAPTIVE_ROUTING.md) | candidate |
| C-RT-2 | Evaluation-driven quality routing at request time | L | H | low | Closed [#37](https://github.com/echoares-lab/ai-gateway/issues/37); [EVAL_DRIVEN_ROUTING.md](./EVAL_DRIVEN_ROUTING.md) | candidate |
| C-RT-3 | Deeper policy engine (WS parity, stricter enforcement, separate service?) | L | H | med | Closed [#38](https://github.com/echoares-lab/ai-gateway/issues/38); [POLICY_ENGINE_AND_ROUTING_REFACTOR.md](./POLICY_ENGINE_AND_ROUTING_REFACTOR.md) | candidate |
| C-RT-4 | MCP visibility and deeper local tool hosting | M | M | med | Closed [#29](https://github.com/echoares-lab/ai-gateway/issues/29); [MCP_TOOL_VISIBILITY.md](./MCP_TOOL_VISIBILITY.md); [ARCHITECTURE.md](./ARCHITECTURE.md) | candidate |
| C-RT-5 | Codex WebSocket frame translation (Option B: translate WS frames to standard HTTP completions for provider-independent routing) | M | M | med | [CLIENT_COMPATIBILITY.md](./CLIENT_COMPATIBILITY.md); ws_router.py | candidate |
| C-RT-6 | Cross-provider reasoning/thinking token normalization (map OpenAI `reasoning_content` ↔ Anthropic `thinking` blocks ↔ Gemini thinking parts, per-client stream + request-param translation, stop hardcoding `reasoning_tokens: 0`) | M | M | high | Design notes (unfiled, not GitHub issue #45 — see caveat below): [epic plan](file:///home/dev/.gemini/antigravity-cli/brain/2712322a-6213-4e3d-bf5d-18fbf77aebf0/client_compatibility_epic_plan.md), [analysis](file:///home/dev/.gemini/antigravity-cli/brain/2712322a-6213-4e3d-bf5d-18fbf77aebf0/agent_compatibility_analysis.md), [reasoning normalization](file:///home/dev/.gemini/antigravity-cli/brain/2712322a-6213-4e3d-bf5d-18fbf77aebf0/reasoning_tokens_normalization.md), [setup guide](file:///home/dev/.gemini/antigravity-cli/brain/2712322a-6213-4e3d-bf5d-18fbf77aebf0/reasoning_setup_guide.md); touches `proxy_normalize.py`, `providers/claude.py`, `providers/gemini.py`, `core/policy/profiles/*.yaml`. Depends on C-MDL-3 (`supports_reasoning` capability field) | candidate |
| C-RT-7 | Context-window-aware request normalization: truncate/prune client history or attachments in `proxy_normalize.py` when routing/fallback resolves to a model with a smaller context window than the client-declared one, instead of surfacing a raw 400 | M | M | med | [agent_compatibility_analysis.md §3.1](file:///home/dev/.gemini/antigravity-cli/brain/2712322a-6213-4e3d-bf5d-18fbf77aebf0/agent_compatibility_analysis.md); touches `proxy_normalize.py`. Depends on C-MDL-3 (`context_window` capability field) | candidate |

**Sequencing note (C-MDL-3, C-RT-6, C-RT-5, C-RT-7):** C-MDL-3 (model-registry capability expansion — `context_window`, `supports_reasoning`) should land first since both C-RT-6 and C-RT-7 consume it rather than guessing/hardcoding capability per model. C-RT-6 (reasoning normalization) is the more isolated, self-contained change and should go next. C-RT-5 (Codex WS frame translation) is higher-complexity/higher-risk (stateful frame parsing) and independent of the other three, so it can land in parallel with or after C-RT-6. C-RT-7 (context-window truncation) is last since it's the lowest-urgency of the four (currently manifests as a hard 400, not silent corruption) and shares the same registry dependency as C-RT-6.

**Caveat on C-RT-6:** the source plan calls this "Epic #45," but GitHub issue #45 is an unrelated merged item (`feat(dev): implement dev stack database sync...`) — no client-compat epic has actually been filed under that number; treat the ID as a Gemini-antigravity-tool internal label, not a real issue link. The plan's third component, "session-based model lock-in," is **already implemented** for the HTTP/policy-engine path via `core/policy/agent_affinity.py` (Redis sticky credential/model-family, rebind on 429) — see closed issues [#38](https://github.com/echoares-lab/ai-gateway/issues/38) and [#125](https://github.com/echoares-lab/ai-gateway/issues/125). It does not cover the WebSocket path, which is the real gap and is already tracked as C-RT-5 above, so it isn't repeated here as a separate candidate.

Suggested atomic children, if/when C-RT-6 is promoted off this list (sequence matters — profile schema and normalization land before the provider-specific stream mapping that depends on them):
1. Add `reasoning_format` key to the client-profile schema (`core/policy/profiles/schema.yaml`) plus values in `cursor.yaml` / `claude.yaml` (`reasoning_content` | `thinking_block` | `markdown_tag` | `strip`).
2. `normalize_reasoning_parameters()` in `proxy_normalize.py`: request-side translation of `thinking.budget_tokens` ↔ `reasoning_effort`, stripped entirely for models/families that don't support reasoning (needs the `supports_reasoning` capability flag from the dependency below).
3. `providers/claude.py`: map OpenAI `reasoning_content` deltas/non-streaming field to Anthropic `thinking` / `thinking_delta` content-block events, and the reverse (Claude `thinking` → OpenAI `reasoning_content`) when Claude is upstream and an OpenAI-shaped client is downstream.
4. `providers/gemini.py`: surface Gemini's thinking parts instead of silently dropping them, using the same internal reasoning-event shape as Claude's adapter.
5. Fix the hardcoded `"reasoning_tokens": 0` in `proxy_responses.py` to parse real usage from whichever provider field applies, so policy-engine budget/quota accounting doesn't leak on reasoning-heavy traffic.
6. Contract tests per client profile for reasoning-heavy streams (mirrors the existing pattern from closed #76/#77) — non-streaming block mapping, streaming delta mapping, and the strip-when-unsupported path.

**Dependency:** steps 2 and 5 need a `supports_reasoning` (and ideally `context_window`) field per model — `config/model-registry.yaml` currently only tracks `supports_tools`/`supports_vision`/`cost_tier`. That schema expansion is already tracked separately as **C-MDL-3**; C-RT-6 should not duplicate it, just consume the field once it exists.


---

## Script-to-service and DX

| ID | Summary | Effort | Risk | Need/fit | Deps / links | Status |
|----|---------|--------|------|----------|--------------|--------|
| C-SVC-1 | Evolve `cliproxy-setup.sh` into management API service | L | M | med | [SCRIPT_TO_SERVICE_ROADMAP.md](./SCRIPT_TO_SERVICE_ROADMAP.md) | candidate |
| C-SVC-2 | `/v1/config/generate` from `gen-client-config.sh` | M | L | med | SCRIPT_TO_SERVICE_ROADMAP | candidate |
| C-SVC-3 | Team/key manager API from `setup_litellm_teams.py` | M | M | unclear | SCRIPT_TO_SERVICE_ROADMAP; tenancy | candidate |
| C-SVC-4 | Unified config admin API (re-implement vs stale `feat/unified-config`) | L | M | med | [UNMERGED_FEATURES.md](./UNMERGED_FEATURES.md) | candidate |

---

## Post-audit hardening leftovers (C-AUD-*)

Historical backlog:
[`issues/archive/post-audit-backlog-2026-06-13.md`](../issues/archive/post-audit-backlog-2026-06-13.md)
(archived). Promote individually; do not claim from the archive.

**Done / superseded (do not reopen):** D-5 (policy lives in
`services/gateway-engine/core/policy/`), D-8 (Gate C opt-in documented), D-13
(test naming sweep), security-hardening epics #305–#323, Stability Foundation
[#377](https://github.com/echoares-lab/ai-gateway/issues/377).

| ID | Summary | Effort | Risk | Need/fit | Audit ref | Status |
|----|---------|--------|------|----------|-----------|--------|
| C-AUD-1 | Require explicit Langfuse/Redis secrets in production | S | M | high | D-1 | candidate |
| C-AUD-2 | Document admin endpoint exposure model (tunnel/WAF) | S | L | high | D-2 | candidate |
| C-AUD-3 | LiteLLM Postgres vs YAML override / drift docs or detector | M | M | high | D-11 | candidate |
| C-AUD-4 | Dev-env compose project collision preflight | S | L | med | D-12 | candidate |
| C-AUD-5 | Narrow broad `except Exception` handlers in gateway-engine | M | M | med | D-6 | candidate |
| C-AUD-6 | Optional WebSocket policy evaluation parity | M | M | med | D-4 | candidate |
| C-AUD-7 | Extend ruff to credential-prober and `scripts/` beyond current Make targets | S | L | med | D-3 | candidate |
| C-AUD-8 | Extract remaining policy hooks from request path / routers | M | M | med | D-7 | candidate |
| C-AUD-9 | Faster local mock iteration (optional skip of heavy clean-db) | S | L | low | D-9 | candidate |
| C-AUD-10 | Integration coverage for catch-all proxy edge cases | M | M | med | D-10 | candidate |

---

## Related docs

- [ROADMAP.md](./ROADMAP.md) — approved Now / Next / Parked only
- [REPO_IMPROVEMENT_WORKFLOW.md](process/REPO_IMPROVEMENT_WORKFLOW.md)
- [UNMERGED_FEATURES.md](./UNMERGED_FEATURES.md)
- [SCRIPT_TO_SERVICE_ROADMAP.md](./SCRIPT_TO_SERVICE_ROADMAP.md)
- [tool-use-eval.md](./tool-use-eval.md) — benchmark plan for Claude Code edit-tool fidelity per backend model; feeds `C-RT-6`/`C-RT-7`
