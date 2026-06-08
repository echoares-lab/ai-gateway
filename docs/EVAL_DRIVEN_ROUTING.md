# Evaluation-Driven Routing — Design Stub

> **Status:** Design only (no runtime behavior change). Implements the Phase 5
> optional scope for Epic #38 issue 38-19 ([#138](https://github.com/echoares-lab/ai-gateway/issues/138)),
> child of roadmap epic [#37](https://github.com/echoares-lab/ai-gateway/issues/37).
> Builds on the policy-engine fallback evaluator (38-8) and adaptive routing
> telemetry plan ([ADAPTIVE_ROUTING.md](./ADAPTIVE_ROUTING.md)).

---

## 1. Problem

Health, latency, and quota signals (38-7, 38-8, ADAPTIVE_ROUTING.md) optimize
for **availability** and **cost**, not **task quality**. Two models with equal
health scores may differ materially on code review, summarization, or tool-use
accuracy. Today fallback ordering is hand-tuned in `litellm-config.yaml` and the
policy-engine `_EMBEDDED_BASELINE` — there is no closed loop from measured
outcomes back into routing weights.

---

## 2. Goal

Close a **quality feedback loop**: capture outcome signals from real workflows,
map them to routing decisions (model, credential pool, fallback chain position),
and tune fallback **weights** (not hard filters) per task category over time.

Non-goals for this stub (full implementation is follow-up):

- Replacing capability hard filters (tools/vision) — quality tuning applies only
  within the eligible candidate set.
- Real-time per-request LLM-as-judge — batch/offline evaluation first.
- Chargeback or spend attribution (see 38-21).

---

## 3. Signal sources

| Signal | Source | Granularity | Phase |
|--------|--------|-------------|-------|
| Trace outcome tags | Langfuse (`success`, `user_retry`, `tool_error`) | per trace / model | 1 |
| Routing decision audit | `routing_decisions_log` (38-16) | per evaluate call | 1 |
| LiteLLM spend / latency | LiteLLM DB + Prometheus | per model / key | 1 |
| Explicit eval datasets | Curated prompts + golden outputs | per task category | 2 |
| Human / agent ratings | Admin console or API | per trace sample | 3 |

Tenant/repo/agent dimensions come from `RoutingContext` (TENANCY.md) and must
be present on stored decisions for segmented quality scoring.

---

## 4. Task categories & KPIs

Initial task categories (extensible via `policy_json.eval.task_categories`):

| Category | Example workflows | Candidate KPIs |
|----------|-------------------|----------------|
| `code_edit` | Cursor agent, patch apply | compile/test pass rate, diff acceptance |
| `code_review` | PR review prompts | finding precision, no false-block |
| `summarization` | doc ingest | ROUGE-lite / human thumbs |
| `tool_orchestration` | MCP-heavy agent turns | tool success rate, steps to completion |
| `chat` | general Q&A | user retry rate, session abandonment |

**Primary routing KPI (v1):** `quality_score(model, task_category)` ∈ [0, 1],
rolling 7-day window, minimum sample size before weight adjustment.

**Guard KPIs (do not regress):** p95 latency, 429 rate, deny/throttle rate,
cost per successful task.

---

## 5. Integration with policy engine (38-8)

The fallback evaluator applies layers in order (see
`services/policy-engine/evaluator/fallback.py`). Evaluation-driven routing
inserts an **optional layer 5b** after health-weighted order (layer 5) and
before cost tier (layer 6):

```text
  … → health-weighted order → eval-quality reorder → cost tier → YAML baseline
```

**Weight model (design):**

```yaml
# policy_profiles.policy_json.eval (illustrative)
eval:
  enabled: false          # default off until Phase 5 implementation
  min_samples: 50
  window_days: 7
  task_category: auto     # derive from request metadata or default chat
  weight_blend: 0.3       # 0 = health-only, 1 = quality-only within eligible set
  model_scores:           # populated by offline job, not hand-edited
    code_edit:
      claude-sonnet-4-6: 0.92
      gpt-5-4: 0.88
      gemini-3-flash: 0.81
```

`rules_applied` tag: `eval:quality_reorder` when layer runs.

Fail-open: missing scores or `enabled: false` → skip layer (current behavior).

---

## 6. Offline feedback job (future implementation)

```text
Langfuse traces + routing_decisions_log
  → aggregate by (task_category, model, repo)
  → compute quality_score + confidence
  → write model_scores into policy_profiles.policy_json.eval
  → optional: emit ADMIN_CONSOLE metric card
```

Job runs on schedule (e.g. nightly); not on request hot path. Uses existing
Postgres + Langfuse API credentials documented in RUNBOOK.md.

---

## 7. Phased implementation issues

| Phase | Deliverable | Depends on |
|-------|-------------|------------|
| **5a (this stub)** | Design doc + issue file + dispatch board | 38-8 done |
| **5b** | `evaluator/quality.py` stub + unit tests (fail-open) | 38-4 gateway-engine wire |
| **5c** | Nightly aggregation script + `model_scores` writer | 38-16 audit log, Langfuse |
| **5d** | Admin console quality card | 38-15 admin trace |

---

## 8. Acceptance criteria (38-19)

- [x] Evaluation/routing feedback loop concept documented (this file)
- [x] Outcome data requirements identified (§3)
- [x] Candidate KPIs defined (§4)
- [x] Phased implementation issues outlined (§7)
- [ ] Runtime quality reorder layer (deferred to 5b+)

---

## Related docs

- [ADAPTIVE_ROUTING.md](./ADAPTIVE_ROUTING.md) — health/latency signals
- [TOKEN_USAGE_ANALYTICS.md](./TOKEN_USAGE_ANALYTICS.md) — Langfuse integration plan
- [TENANCY.md](./TENANCY.md) — trace metadata dimensions
- `issues/policy-engine-38-19-eval-routing.md` — issue tracker
