# Tool-Use & Cross-Model Compatibility Eval Suite

Runbook for the benchmark harness that measures how well Claude Code's
file-editing tools (and, protocol-level, other client wire formats) hold up
when the AI Gateway routes a session to a non-native backend model.

Design background: [`docs/tool-use-eval.md`](../../docs/tool-use-eval.md).
Findings feed back into [`docs/FEATURE_CANDIDATES.md`](../../docs/FEATURE_CANDIDATES.md)
(`C-RT-5`, `C-RT-6`, `C-RT-7`).

---

## What's here

```
scripts/eval/
  tool_use_bench.py          # Claude Code Edit/MultiEdit/Write fidelity harness
  protocol_checks.py         # Direct gateway protocol checks (reasoning tokens,
                              # streaming tool-calls) — no client CLI involved
  fixtures/
    single_edit/              # one unique-string replacement
    near_duplicate_edit/      # exact-match discipline (identical text in 3 places)
    multi_edit_sequence/      # 3 ordered edits in one file
    read_edit_verify_loop/    # read one file, compute a value, edit another
    new_file_write/           # create a new file from a spec
  results/                    # raw JSONL logs from past runs, kept for history
```

Each fixture directory contains:
- the seed file(s) the scratch repo starts from
- `task_prompt.txt` — the instruction given to the client
- `checker.py` — a `check(scratch_dir) -> (bool, reason)` function that
  verifies the *outcome* (not the prose), so it works across models that
  phrase things differently but should produce the same file state.

---

## 1. Claude Code tool-use fidelity (`tool_use_bench.py`)

**What it tests:** does `claude -p` reliably apply file edits via `Edit`/
`MultiEdit`/`Write` when the backend model behind the gateway isn't Claude?

**Requires:** a running dev-slot gateway stack and the `claude` CLI installed
locally (`which claude`).

```bash
# 1. Standard dev-stack setup (see CLAUDE.md / AGENTS.md session workflow)
git worktree add /home/dev/worktrees/ai-gateway-tool-use-eval feat/tool-use-eval
ln -s /home/dev/repos/ai-gateway/.env /home/dev/worktrees/ai-gateway-tool-use-eval/.env
cd /home/dev/worktrees/ai-gateway-tool-use-eval
./dev-env.sh start 1        # gateway-engine:4010, litellm:4011, cliproxy:8327

# 2. Run the harness
KEY=$(grep -m1 ^LITELLM_MASTER_KEY .env | cut -d= -f2-)
python3 scripts/eval/tool_use_bench.py \
  --models claude-sonnet-4-6,gpt-5-4,gemini-3-flash \
  --tasks single_edit,near_duplicate_edit,multi_edit_sequence,read_edit_verify_loop,new_file_write \
  --repeats 2 \
  --api-key "$KEY" \
  --base-url http://localhost:4010 \
  --out scripts/eval/results/run_$(date +%Y%m%d).jsonl

# 3. Tear down when done
./dev-env.sh stop 1
```

**Flags:**
| Flag | Default | Notes |
|---|---|---|
| `--models` | `claude-sonnet-4-6,gpt-5-4,gemini-3-flash` | comma-separated; must match `config/model-registry.yaml` model IDs (no `AI-Gateway:` prefix — the harness adds it) |
| `--tasks` | `single_edit` | comma-separated task/fixture directory names |
| `--repeats` | `2` | runs per (model, task) cell — each run consumes real CLIProxy quota, keep this small for a first pass |
| `--timeout` | `120` | seconds per individual `claude -p` invocation |
| `--base-url` | `http://localhost:4010` | point at whichever dev slot is running |
| `--api-key` | *(required)* | `LITELLM_MASTER_KEY` from `.env` |
| `--out` | `tool_use_bench_results.jsonl` | raw per-run JSONL log |

**Output:** a markdown scorecard (`model × task → pass/total`, plus a count
of runs excluded because LiteLLM silently substituted a fallback model — see
"Fallback substitution" below) printed to stdout, and the full JSONL log for
post-hoc inspection (every run's stdout/stderr tail, `stop_reason`,
`modelUsage` keys, checker failure reason).

**Fallback substitution guard:** each run's actual served model is read from
the response's `modelUsage` keys and compared to the model requested. If
LiteLLM's `fallbacks:` list (`litellm-config.yaml`) silently substituted a
different model — which only happens if the primary deployment errored —
that run is excluded from the pass/fail scorecard rather than misattributed.
Check the JSONL log's `fallback_substituted` field if the exclusion count is
nonzero.

**Adding a new task:** create `scripts/eval/fixtures/<name>/` with seed
file(s), `task_prompt.txt`, and `checker.py` (same `check()` signature as the
existing fixtures). No harness code changes needed — `--tasks <name>` picks
it up automatically.

---

## 2. Protocol-level checks (`protocol_checks.py`)

**What it tests:** gateway-level translation correctness for the two gaps
identified in `docs/FEATURE_CANDIDATES.md` `C-RT-6` — independent of any
client CLI, by hitting the gateway's HTTP endpoints directly:

1. **Reasoning-token accounting** — confirms whether `output_tokens_details.reasoning_tokens`
   (Responses API) / equivalent usage fields are ever nonzero for a model
   that actually performs extended reasoning, or whether they're still
   hardcoded to `0` (the bug found in `proxy_responses.py` during the
   original review).
2. **Streaming tool-call delta integrity** — sends a tool-calling request
   with `stream=true` against each model family and confirms the assembled
   tool-call arguments (accumulated across SSE chunks) are valid JSON
   matching the tool's schema, per client wire format (OpenAI
   `/v1/chat/completions`, Anthropic `/v1/messages`).

```bash
KEY=$(grep -m1 ^LITELLM_MASTER_KEY .env | cut -d= -f2-)
python3 scripts/eval/protocol_checks.py \
  --models claude-sonnet-4-6,gpt-5-4,gemini-3-flash \
  --base-url http://localhost:4010 \
  --api-key "$KEY" \
  --out scripts/eval/results/protocol_$(date +%Y%m%d).jsonl
```

This does not require `claude`/`cursor-agent` — it's plain `httpx` calls, so
it's the right tool for testing "does the gateway handle model X correctly"
independent of which client is asking.

---

## 3. Cursor (manual, not automated)

`cursor-agent` (the headless CLI) **cannot** be pointed at this gateway — it
authenticates to Cursor's own hosted backend (`api2.cursor.sh`, a proprietary
protobuf/RPC service) and has no base-URL override for actual model
inference calls. The real "Cursor → AI-Gateway" path is the IDE-level custom
OpenAI-compatible provider setting described in `CLAUDE.md` ("Cursor
Integration"), which is account-scoped inside the full desktop/IDE app, not
scriptable from a CLI.

To evaluate Cursor manually against this suite:

1. In the real Cursor IDE, configure a custom OpenAI-compatible model
   provider pointed at the dev slot (`http://localhost:4010/v1`, model names
   prefixed `AI-Gateway:`), per `CLAUDE.md`.
2. Open (or point Cursor at) a scratch repo seeded from one of
   `scripts/eval/fixtures/<task>/` (copy the seed files + `task_prompt.txt`
   content as your chat prompt — don't include `checker.py` in what Cursor
   sees).
3. Run the prompt against each target model through Cursor's agent mode.
4. Run the fixture's checker against the resulting files:
   `python3 scripts/eval/fixtures/<task>/checker.py <your-scratch-dir>`.
5. Record the result the same way the JSONL log does (model, task, pass/fail,
   reason) so it can be folded into the same scorecard format by hand.

We don't need Cursor's internal client-side response-handling logic to
validate this — only (a) whether the gateway translated the request/response
correctly (check gateway/LiteLLM logs or a Langfuse trace for the session if
enabled) and (b) whether the resulting file edit is correct (the checker
handles that part, same as the automated harness).

---

## Known limitations

- Small sample sizes (2 repeats/cell) are for cheap signal, not statistical
  rigor — treat results as "worth investigating further" or "no signal
  found," not confidence intervals.
- The harness only covers the `Edit`/`MultiEdit`/`Write` tool-use path and
  the two protocol gaps above. It does not cover MCP tool visibility,
  context-window truncation (`C-RT-7`), or Codex WebSocket translation
  (`C-RT-5`) — those need separate harnesses if/when those candidates are
  promoted.
- Every run costs real CLIProxy OAuth quota against whichever provider is
  targeted. Don't run large `--repeats`/`--tasks`/`--models` combinations
  without checking quota headroom first (`./cliproxy-setup.sh quota-summary`).
