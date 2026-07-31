# Claude Code Tool-Use Fidelity Benchmark

> **Delivered benchmark reference.** The model-forcing and initial harness work
> merged in [PR #440](https://github.com/echoares-lab/ai-gateway/pull/440), with
> protocol/benchmark integration completed in
> [PR #484](https://github.com/echoares-lab/ai-gateway/pull/484). There is no
> benchmark epic: unrelated [PR #420](https://github.com/echoares-lab/ai-gateway/pull/420)
> belongs to the completed CLIProxy work.

---

## 1. Problem

Claude Code's file-editing tools (`Edit`, `MultiEdit`, `Write`) rely on the
model reproducing existing file content **exactly** — `Edit`'s `old_string`
must byte-for-byte match a unique span in the target file — and on correctly
sequencing multiple tool calls in agentic loops (read → edit → verify). This
is a tool-use fidelity skill, not a wire-format compatibility question: the
gateway already transcodes tool-call schemas correctly across providers
(OpenAI `tool_calls` ↔ Anthropic `tool_use` ↔ Gemini `functionCall`). What's
unverified is whether **non-Claude backends, reached by routing a Claude Code
session through the gateway to a different model, actually succeed at this
task at an acceptable rate**.

Today this is a guess. Nobody has measured Edit-tool apply success, `old_string`
exact-match failure modes, or multi-edit sequencing accuracy per backend model.
Any future policy decision about safe fallback targets for Claude Code sessions
needs benchmark evidence and a newly promoted candidate with atomic issues.

---

## 2. Goal

Produce a **per-model fidelity scorecard** for Claude Code's tool-use pattern,
using the same client (Claude Code itself) against different backend models
routed through the gateway, so that:

- Cross-provider fallback policy for Claude Code sessions can be based on
  measured apply-success rates, not assumption.
- `agent_compatibility_analysis.md`'s "Claude Code XML edit tags" claim is
  either confirmed, corrected, or retired from future planning.
- Findings can shape a future fallback-policy candidate (for example, a
  same-family tool-use requirement in addition to context-window limits).

Non-goals:

- Building any new gateway feature. This is a measurement exercise only.
- Benchmarking non-edit tool use (search, bash, MCP tools) — scoped to the
  Edit/MultiEdit/Write path specifically, since that's the concrete claim
  under test.
- Statistically rigorous eval infra (bootstrapped CIs, judge-model scoring).
  A first pass with clear pass/fail apply criteria is enough to decide the
  policy question.

---

## 3. Candidate models

Route each run through a local dev slot's LiteLLM → CLIProxy, varying only the
target model. Use `config/model-registry.yaml` families as the grouping:

| Family | Candidate model(s) | Role |
|---|---|---|
| `anthropic` | `claude-sonnet-4-6`, `claude-haiku-4-5` | Control group (native fit) |
| `openai` | `gpt-5-4`, `gpt-oss-120b-medium` | Cross-family, strong tool-use reputation |
| `gemini` | `gemini-3-flash` | Cross-family, weaker native tool-call ergonomics per `gemini.py` heuristics |

Extend the list opportunistically (e.g. a second OpenAI-family model at a
different size) once the harness works — the harness should not hardcode the
model list, it should read `config/model-registry.yaml` and accept a
`--models` filter.

---

## 4. Environment: isolated dev stack

Use the repo's existing isolated dev-stack tooling — no new infrastructure.
Per `CLAUDE.md` / `dev-env.sh`, this is already the supported way to run a
disposable gateway stack without touching the stable slot on port 4000:

```bash
# One-time: worktree for the benchmark harness code
mkdir -p /home/dev/worktrees
cd /home/dev/repos/ai-gateway && git checkout main
git worktree add /home/dev/worktrees/ai-gateway-tool-use-eval -b feat/tool-use-eval
ln -s /home/dev/repos/ai-gateway/.env /home/dev/worktrees/ai-gateway-tool-use-eval/.env
cd /home/dev/worktrees/ai-gateway-tool-use-eval

# Isolated 3-container stack (gateway-engine + litellm + cliproxy) in slot 1
./dev-env.sh start 1        # gateway-engine:4010, litellm:4011, cliproxy:8327
```

Point Claude Code itself at the dev slot instead of the stable stack for the
benchmark runs, via `ANTHROPIC_BASE_URL` (or the repo's client-config
generator):

```bash
export ANTHROPIC_BASE_URL="http://localhost:4010"
export ANTHROPIC_API_KEY="<virtual key scoped for the dev slot>"
```

Everything the benchmark does (seed a scratch repo, run Claude Code
non-interactively against a task, force the target model via routing/header
override, inspect the result, tear down) happens against slot 1 so it never
touches the stable stack or other agents' slots. `./dev-env.sh stop 1` +
`git worktree remove` cleans up afterward, matching the standard session
workflow in `CLAUDE.md`.

**Forcing the target model per run:** the harness needs a way to pin a given
Claude Code invocation to a specific backend model without relying on the
gateway's normal routing/fallback logic (which would defeat the point — we
want to control the independent variable). Two options, in order of
preference:

1. If the client-facing model alias already lets a caller select a specific
   `AI-Gateway:<model>` name directly (bypassing policy-engine routing
   decisions), use that — check `services/gateway-engine/api/proxy_routing.py`
   for how explicit model selection vs. policy-driven routing interact.
2. Otherwise, add a dev-only escape hatch (e.g. an `X-Force-Model` header
   honored only when `POLICY_ENGINE_ENABLED=false` or a dev-stack env flag) —
   should not ship as a production feature, scope it to the eval harness.

Resolve which of these applies as the first implementation step (see §7),
since it gates everything else.

---

## 5. Benchmark tasks

A small, fixed set of scratch-repo tasks that exercise the tool-use pattern
under test, seeded fresh per run so results aren't contaminated by prior
state:

| Task | Exercises | Pass criteria |
|---|---|---|
| `single-edit` | One `Edit` call, unique `old_string` match in a ~200-line file | File changes exactly as intended; no `old_string` not found error |
| `near-duplicate-edit` | `Edit` where the target span is *almost* unique (tests exact-match discipline) | Correct occurrence edited, not a lookalike elsewhere in the file |
| `multi-edit-sequence` | `MultiEdit` with 3+ ordered edits in one file | All edits applied, in order, no partial-apply state left behind |
| `read-edit-verify-loop` | Read → Edit → Read-back agentic loop (2+ tool round-trips) | Loop terminates correctly; model correctly interprets its own prior edit when re-reading |
| `new-file-write` | `Write` a new file from scratch given a spec | File created with expected content; no attempt to `Edit` a nonexistent file |

Each task ships as a fixture: starting repo state (a tiny seed dir checked
into the harness, not the main repo) + task prompt + a scriptable checker
(diff against expected end-state, or a regex/AST check where exact text
match is too strict for a non-Claude model's slightly different phrasing).

---

## 6. Metrics

Per (model × task) cell:

- **Apply success rate**: tool call executed without a hard error
  (`old_string` not found, file not found, malformed args) — count over N
  repeated runs (recommend N=5 per cell to see variance, not just one sample).
- **Correctness rate**: apply succeeded *and* the checker confirms the
  resulting file state matches the task's intent (a model can "succeed" at
  the tool call but edit the wrong thing).
- **Sequencing integrity** (multi-edit/loop tasks only): all steps completed
  in the expected order with no skipped/duplicated tool calls.
- **Retry behavior**: does the model self-correct after a tool error (re-read
  the file, retry with a corrected `old_string`) or does it stall/give up?

Report as a simple scorecard table (model rows × task columns, cell =
success/N), not a single aggregate score — the point is to see *where*
specific models diverge, not to produce one number.

---

## 7. Re-run and extension steps

1. Confirm the model-forcing behavior (§4) against the current
   `proxy_routing.py` before relying on a new benchmark result.
2. Reuse or extend `scripts/eval/tool_use_bench.py`: seed a scratch repo per
   task, invoke Claude Code non-interactively against a dev slot with the
   model pinned, capture the transcript/tool calls, run the task checker, and
   record the metrics from §6.
3. Wire it to `./dev-env.sh start 1` / `stop 1` for setup/teardown so a full
   run is a single invocable script, not a manual multi-step process.
4. Run the full (model × task × N repeats) matrix once end-to-end on the
   control group (`anthropic` family) first to validate the harness itself
   isn't the source of failures, before drawing conclusions about other
   families.
5. Run the cross-family models, produce the scorecard.
6. Record any new scope as a candidate first; do not reopen delivered
   benchmark, reasoning, or context-window work in place.

---

## 8. Out of scope / open questions

- Whether to run this as a one-off manual exercise or wire it into CI as a
  recurring regression check once model versions change — decide after the
  first manual pass shows how noisy/expensive it is.
- Whether non-edit tool use (bash, search, MCP) deserves the same treatment —
  likely yes eventually, but this stub is scoped to the specific claim under
  test (edit-tool fidelity), not a general tool-use eval suite.
- Judge-model or human scoring for cases where the checker can't cleanly
  determine correctness (e.g. a model makes a *reasonable but different*
  edit than the fixture expects) — start with tasks precise enough to avoid
  needing this; expand only if early runs show it's necessary.

---

## Related docs

- [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) — current unapproved
  inventory for any follow-on work.
- [CLIENT_COMPATIBILITY.md](./CLIENT_COMPATIBILITY.md) — supported client
  matrix and profile definitions.
- `CLAUDE.md` — dev-stack workflow (`dev-env.sh`) this design builds on.
