# AI Gateway — Agent Instructions

See the [API Documentation System](docs/API_DOCUMENTATION.md) for technical endpoint references.
**Mandatory**: Any new API endpoints created or discovered must be documented in `docs/openapi/` and registered in the system.

These instructions apply to **any AI coding agent** working in this repo
(Claude Code, Cursor Agent, Codex, Amp, or similar). For deep-dive detail
on architecture and commands, see `CLAUDE.md`. For operational procedures,
see `RUNBOOK.md`.

Repo improvement and PR processing are governed by:
- `REPO_IMPROVEMENT_WORKFLOW.md` — process rules (discovery, approval, claim, PR, merge, closeout).
- `TESTING_AND_PROMOTION_POLICY.md` — gate definitions (A/B/C/D), risk tiers, parallel-agent isolation.
- `REPO_IMPROVEMENT_APPENDIX.md` — this repo's branch policy, environment slots, and test commands.
- `AGENT_DISPATCH.md` — the copy-paste prompt agents run to claim an issue and ship it.
- `packages/repo-improvement-kit/` — portable source for the above; see its `README.md` for deployment.

---

## Stack at a glance

All services run as Docker containers — no `requirements.txt` or `package.json`
to install. Docker must be running before any `docker compose` commands.

| Service | Port | Role |
|---------|------|------|
| gateway-engine | 4000 | Public entry point — all client traffic |
| litellm | 4001 | Model proxy UI |
| cliproxy | 8317 | OAuth relay to LLM providers |
| cpa-manager | 18317 | Usage analytics UI |
| langfuse-web | 3000 | Observability UI |
| postgres | 5432 | LiteLLM DB (localhost only) |
| redis | 6379 | Cache (localhost only) |

The stable production stack runs on port 4000. Dev stacks use slots (port 4010, 4020, …).

---

## Environment requirements

- `.env` must exist (copy from `.env.example`); it is gitignored — never commit it
- `~/.cliproxy/config.yaml` and `~/.cli-proxy-api/` must exist for cliproxy volume mounts
- On a remote server: open SSH port forwards before OAuth login (see `RUNBOOK.md`)

---

## ⚠️ The non-negotiable rule

**Never edit files while the stable stack (port 4000) is your working directory.**

The stable stack serves live traffic. All development must happen in an isolated
worktree with its own dev stack slot. This is enforced by convention, not by tooling —
agents must follow it.

---

## Development workflow

Every session follows this sequence. Do not skip steps.

### Step 1 — Create a feature worktree

```bash
# Always branch off main
mkdir -p /home/dev/worktrees
git checkout main
git worktree add /home/dev/worktrees/ai-gateway-<feature> -b feat/<feature>
ln -s /home/dev/repos/ai-gateway/.env /home/dev/worktrees/ai-gateway-<feature>/.env
cd /home/dev/worktrees/ai-gateway-<feature>
```

### Step 2 — Start an isolated dev stack

```bash
# Find a free slot first
./dev-env.sh list

# Start your slot (1, 2, 3, …  — slot 0 is the stable stack, reserved)
./dev-env.sh start 1
```

Dev slots map to ports:
| Slot | gateway-engine | litellm UI | cliproxy |
|------|-----------|------------|----------|
| 1 | :4010 | :4011 | :8327 |
| 2 | :4020 | :4021 | :8337 |

### Step 3 — Make changes (hot-reload is automatic)

- `services/gateway-engine/main.py` edits → uvicorn reloads in ~1 second (no action needed)
- `litellm-config.yaml` edits → litellm-reloader detects and restarts in ~10 seconds
- `Dockerfile` or pip dependency changes → `./dev-env.sh rebuild <slot>`

### Step 4 — Test after each significant change (Gate A)

Run unit tests inside the dev gateway-engine container or via Make:

```bash
docker exec aidev1-gateway-engine-1 pytest test_gateway-engine*.py -v
# or locally without a running stack:
make test-unit
```

All unit tests must pass before continuing. Fix failures before moving on.

For mock integration during development (Gate B):

```bash
make test-mock    # mock stack on slot 9, 0 skips enforced
```

### Step 5 — Commit checkpoints

Commit before risky changes and at logical stopping points — not just at the end.
This keeps session history recoverable.

```bash
git add -p
git commit -m "feat(scope): short imperative description"
```

See [Commit message format](#commit-message-format) below.

### Step 6 — Pre-PR verification (Gates A + B)

Before opening a PR, run the fast local tier (mirrors required CI):

```bash
make test-fast    # lint + unit + mock integration
```

For **high-risk** changes (auth, `litellm-config.yaml`, compose, cliproxy), also run Gate C:

```bash
make test-e2e     # real OAuth stack + smoke subset
# or: gh pr edit <num> --add-label run-e2e   # triggers CI real-provider-e2e
```

Resolve all failures before merging. Do not proceed with a broken dev stack.

### Step 7 — Open a PR to main (required)

**Never push directly to main.** Open a PR so CI runs and leaves a review trail.

```bash
gh pr create --base main --head feat/<feature> \
  --title "feat(scope): description" \
  --body "$(cat <<'EOF'
## Summary
- What changed and why

## Test plan
Risk level: medium

### Gate A + B (required)
- [ ] `make test-fast` pass (lint, unit, mock integration)

### Gate C (high-risk only)
- [ ] `make test-e2e` or PR label `run-e2e`

### Gate D (post-merge — not pre-merge)
- [ ] Record in closeout after merge to main

🤖 Generated with Claude Code
EOF
)"
```

Wait for required CI checks to pass:
- `lint-and-syntax`, `unit-tests`, `multi-repo-isolation`, `mock-integration`

If `main` moved since your last green CI (e.g. a dependency PR merged), rebase first —
see [Parallel agents, rebase, and stacking](#parallel-agents-rebase-and-stacking).

Then merge:

```bash
gh pr merge --merge --auto   # or --squash; use manual --merge if auto-merge is disabled
git checkout main
git pull origin main
```

### Step 8 — Gate D: verify stable stack after merge

From the **stable worktree** (`/home/dev/repos/ai-gateway` on `main`):

```bash
git pull origin main
./cliproxy-setup.sh health
./cliproxy-setup.sh test claude-sonnet-4-5-20250929
./cliproxy-setup.sh test gemini-3-flash
./cliproxy-setup.sh test gpt-5-4
```

All three model tests must return a valid response. Record results in the issue closeout.
If any fail, investigate and fix before the session ends.

### Step 9 — Clean up (after PR merge only)

**When:** Run cleanup only after the PR is merged to `main` and Gate D passes (Step 8).
Do not tear down the worktree or dev stack while the PR is still open — you may need
to push fixes or rebase.

**Closeout checklist:**

```bash
# 1. Stop the isolated dev stack (use your claimed slot, not 0)
./dev-env.sh stop <slot>

# 2. Remove the feature worktree from the main repo checkout
cd /home/dev/repos/ai-gateway
git worktree remove /home/dev/worktrees/ai-gateway-<feature>

# 3. Delete the local feature branch (only after merge)
git branch -d feat/<feature>

# 4. Verify nothing is left behind
git worktree list
./dev-env.sh list
```

**If `git worktree remove` fails** (dirty tree, uncommitted changes, or running containers):

```bash
# Commit or stash changes in the feature worktree first
cd /home/dev/worktrees/ai-gateway-<feature>
git status
git stash push -m "cleanup-stash"   # or commit and push if still needed for the PR

# Force-stop the dev stack if containers are still running
./dev-env.sh stop <slot>

# Retry removal; use --force only when the directory is clean but metadata is stale
cd /home/dev/repos/ai-gateway
git worktree remove /home/dev/worktrees/ai-gateway-<feature>
# git worktree remove --force /home/dev/worktrees/ai-gateway-<feature>  # last resort

git worktree prune
```

**Coordinator / parent agent:** When dispatching subagents, verify cleanup before
closing the parent epic or session: `git worktree list` shows only the stable checkout,
`./dev-env.sh list` shows no orphaned slot for the claim, and the issue closeout
comment records the cleanup.

---

## Parallel agents, rebase, and stacking

When multiple agents work the same repo concurrently, enforce **one issue = one agent
= one slot = one worktree**. See `REPO_IMPROVEMENT_WORKFLOW.md` §8–10 and
`AGENT_DISPATCH.md` for claim conventions.

### Slot and claim rules

- Run `./dev-env.sh list` **before** `./dev-env.sh start <slot>` — never use slot 0.
- Record slot, worktree path, branch, and a unique `Claim-ID` in the issue claim comment.
- `Claim-ID` must identify the **agent session**, not just the GitHub account
  (e.g. `Claim-ID: cursor-epic1-2-20260606T143000Z`).

### Branching with dependencies

| Situation | Branch from |
|-----------|-------------|
| No open dependency, or dependency already merged to `main` | `main` |
| Dependency PR is open and stable; your issue explicitly stacks on it | The dependency feature branch (e.g. `feat/epic-1-1`) |

**Before claiming:** Poll dependency state — issue closed, or `gh pr view <num> --json state,mergedAt`.

```bash
gh issue view <dep-issue> --json state,closed
gh pr list --repo echoares-lab/ai-gateway --head feat/<dep-branch> --json state,mergedAt
```

Do not start implementation on a stacked branch until the dependency PR is reviewable
and CI-green unless the issue explicitly allows parallel draft work.

### Rebase after a dependency merges

When your branch was stacked on a dependency that has since merged to `main`, rebase
onto current `main` **before** enabling merge (and after CI on the dependency PR completes):

```bash
cd /home/dev/worktrees/ai-gateway-<feature>
git fetch origin
git rebase origin/main
# resolve conflicts, then:
git add <resolved-files>
git rebase --continue
make test-fast    # re-verify after conflict resolution
git push --force-with-lease origin feat/<feature>
```

Re-run `make test-fast` after any conflict resolution. Example: Epic 1.2 rebased onto
`main` after Epic 1.1 merged, then force-pushed with `--force-with-lease`.

### Hotspot serialization

If two issues touch the same hotspot (e.g. `services/gateway-engine/**`,
`litellm-config.yaml`), **serialize** them:

- Declare `Depends on: #N` in the issue, or
- Stack the second PR on the first branch until the first merges, then rebase onto `main`.

Do not let two agents edit the same hotspot without an explicit dependency or stack order.

### CI flakes and merge fallback

- If CI `mock-integration` fails on infra (timeouts, runner issues) but local Gate B passes,
  run `make test-mock` in the feature worktree and note the result in the PR thread.
- Auto-merge may be disabled on the repo. If `gh pr merge --auto` does nothing, merge
  manually once required checks are green:

```bash
gh pr checks <num> --watch
gh pr merge <num> --merge
```

### Stable worktree hygiene

Gate D runs from `/home/dev/repos/ai-gateway` on `main`. Before `git pull origin main`:

```bash
cd /home/dev/repos/ai-gateway
git status    # must be clean — no local edits on stable
git pull origin main
```

Never leave uncommitted changes in the stable worktree; they block pulls and Gate D.

---

## Test commands reference

| Gate | Command | When |
|------|---------|------|
| A — unit | `make test-unit` (gateway-engine `-n auto` + policy-engine) | After each significant change |
| A — lint | `make lint` | Before commit / push |
| B — mock integration | `make test-mock` or `make test-fast` | Before PR; required CI parity |
| C — real providers | `make test-e2e` or label `run-e2e` | Opt-in only (high-risk changes) |
| D — stable smoke | `./cliproxy-setup.sh test <model>` + `health` | After merge to main (+ advisory `post-merge-gate-d` workflow) |
| Full integration | `./dev-env.sh test <slot>` | When Gate C needs broader coverage |
| YAML validation | `python3 -c "import yaml; yaml.safe_load(open('litellm-config.yaml'))"` | After editing litellm-config.yaml |

Optional pre-push hook: `make lint && make test-unit` (see `.githooks/pre-push`).

---

## Commit message format

The repo uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short imperative description>
```

| Type | Use for |
|------|---------|
| `feat` | New capability |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `chore` | Maintenance, deps, tooling |
| `refactor` | Code restructure, no behaviour change |
| `test` | Test additions/changes |

Examples from this repo:
```
feat(observability): add Prometheus metrics endpoint to gateway-engine
fix(reliability): discriminate sync-models probe failures by HTTP status code
docs: update stale AGENTS/WORKTREES/RUNBOOK to reflect current state
```

---

## What NOT to do

- ❌ **Do not push directly to `main`** — always via PR with CI passing
- ❌ **Do not edit files in the stable worktree** (`/home/dev/repos/ai-gateway`) during development
- ❌ **Do not create feature worktrees under `/home/dev/repos/` or inside the repo** (use `/home/dev/worktrees/ai-gateway-<feature>` — see `WORKTREES.md`)
- ❌ **Do not skip unit tests** after changes to `services/gateway-engine/main.py`
- ❌ **Do not hardcode API keys** in `litellm-config.yaml` — use `os.environ/CLIPROXY_API_KEY`
- ❌ **Do not set `CACHE_ENABLED=true`** in production — LiteLLM's auth-aware cache is preferred
- ❌ **Do not force-push** to `main`
- ❌ **Do not merge with uncommitted changes** in the worktree
- ❌ **Do not touch `~/.cli-proxy-api/` directly** — dev stacks seed their own isolated auth volume
- ❌ **Do not remove a worktree or stop its dev stack before the PR merges** — keep the environment for fixes and rebase
- ❌ **Do not share a dev slot** between concurrent agents without an explicit handoff in the issue thread
- ❌ **Do not leave the stable worktree dirty** — it blocks `git pull` and Gate D verification

---

## Linting

```bash
pip install ruff                                                   # one-time install
ruff check services/gateway-engine/main.py                            # lint
ruff format --check services/gateway-engine/main.py                   # format check
bash -n cliproxy-setup.sh                                         # shell syntax
python3 -c "import yaml; yaml.safe_load(open('litellm-config.yaml'))"  # YAML
```

Pre-commit hooks (install once: `pip install pre-commit && pre-commit install`)
cover ruff, YAML validation, and hardcoded API key detection automatically.

Optional pre-push hook (Gate A fast checks): `git config core.hooksPath .githooks`
runs `make lint && make test-unit` before each push.

CI (GitHub Actions `.github/workflows/ci.yml`) uses tiered gates on every push/PR to `main`:

- **Required — Fast (A):** `lint-and-syntax`, `unit-tests`, `build-gateway-engine`
- **Required — Conditional:** `mock-integration`, `multi-repo-isolation`, path-filtered service tests
- **Advisory (Gate C — opt-in):** `real-provider-e2e` via `run-e2e` label or `workflow_dispatch` only (hotspot auto-trigger paused pending e2e refactor)
- **Advisory:** `nightly-integration`, `post-merge-gate-d`, `hotspot-e2e-reminder`

See `docs/TESTING.md`, `TESTING_AND_PROMOTION_POLICY.md`, and `REPO_IMPROVEMENT_APPENDIX.md` for full gate mapping.

---

## Regression prevention guardrails

| Risk | Guard |
|------|-------|
| Broken YAML config | Pre-commit hook + CI `lint-and-syntax` |
| Hardcoded secrets committed | `.githooks/prevent-hardcoded-keys.sh` |
| Lint regressions | `ruff` in CI on every push |
| Gateway Engine logic broken | Unit tests (`test_gateway-engine*.py`) in CI |
| Multi-repo isolation broken | `multi-repo-isolation` job in CI |
| Wire-format / routing broken | `mock-integration` job (0 skips) |
| Real provider regressions | Gate C: opt-in via `run-e2e` label or nightly schedule |
| Post-merge production drift | Gate D: stable smokes + advisory `post-merge-gate-d` workflow |
| Stable stack taken down | Worktree isolation (step 1) |
| Direct push bypasses review | Branch protection + PR requirement |
| Image version drift | Pinned in docker-compose files; upgrade via PR + test |
| Cross-user cache hits | `CACHE_ENABLED=false` default in gateway-engine |
| Two agents on same slot | Slot registry in claim comments; `./dev-env.sh list` |
| Orphaned worktrees / occupied slots | Post-merge cleanup checklist (Step 9); coordinator verifies `git worktree list` |
| Dirty stable worktree blocks Gate D | Never edit stable checkout; `git status` before `git pull` |
| Stacked PR conflicts after dependency merge | Rebase onto `origin/main`, `make test-fast`, `--force-with-lease` push |

---

## Architecture (brief)

```
Client → gateway-engine:4000 → litellm:4000 (internal) → cliproxy:8317
                                                         ├── Anthropic (Claude OAuth)
                                                         ├── OpenAI (Codex OAuth)
                                                         ├── Antigravity (Gemini OAuth)
                                                         ├── xAI (Grok OAuth)
                                                         └── Moonshot (Kimi OAuth)
```

The `gateway-engine` is the real entry point. It handles format translation
(Responses API → Chat Completions, Gemini CLI format, Claude Messages API)
and adds the `AI-Gateway:` model prefix. See `CLAUDE.md` for full detail.
