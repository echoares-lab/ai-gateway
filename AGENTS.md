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
| translator | 4000 | Public entry point — all client traffic |
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
| Slot | translator | litellm UI | cliproxy |
|------|-----------|------------|----------|
| 1 | :4010 | :4011 | :8327 |
| 2 | :4020 | :4021 | :8337 |

### Step 3 — Make changes (hot-reload is automatic)

- `translator.py` edits → uvicorn reloads in ~1 second (no action needed)
- `litellm-config.yaml` edits → litellm-reloader detects and restarts in ~10 seconds
- `Dockerfile` or pip dependency changes → `./dev-env.sh rebuild <slot>`

### Step 4 — Test after each significant change (Gate A)

Run unit tests inside the dev translator container or via Make:

```bash
docker exec aidev1-translator-1 pytest test_translator*.py -v
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

Then merge:

```bash
gh pr merge --merge   # or --squash for a single clean commit
git checkout main
git pull origin main
```

### Step 8 — Gate D: verify stable stack after merge

From the **stable worktree** (`/home/dev/repos/ai-gateway` on `main`):

```bash
git pull origin main
./cliproxy-setup.sh health
./cliproxy-setup.sh test claude-sonnet-4-6
./cliproxy-setup.sh test gemini-3-flash
./cliproxy-setup.sh test gpt-5-4
```

All three model tests must return a valid response. Record results in the issue closeout.
If any fail, investigate and fix before the session ends.

### Step 9 — Clean up

```bash
./dev-env.sh stop 1
cd /home/dev/repos/ai-gateway
git worktree remove /home/dev/worktrees/ai-gateway-<feature>
git branch -d feat/<feature>
```

---

## Test commands reference

| Gate | Command | When |
|------|---------|------|
| A — unit | `make test-unit` or `docker exec aidev1-translator-1 pytest test_translator*.py -v` | After each significant change |
| A — lint | `make lint` | Before commit / push |
| B — mock integration | `make test-mock` or `make test-fast` | Before PR; required CI parity |
| C — real providers | `make test-e2e` or label `run-e2e` | High-risk changes only |
| D — stable smoke | `./cliproxy-setup.sh test <model>` + `health` | After merge to main |
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
feat(observability): add Prometheus metrics endpoint to translator
fix(reliability): discriminate sync-models probe failures by HTTP status code
docs: update stale AGENTS/WORKTREES/RUNBOOK to reflect current state
```

---

## What NOT to do

- ❌ **Do not push directly to `main`** — always via PR with CI passing
- ❌ **Do not edit files in the stable worktree** (`/home/dev/repos/ai-gateway`) during development
- ❌ **Do not create feature worktrees under `/home/dev/repos/` or inside the repo** (use `/home/dev/worktrees/ai-gateway-<feature>` — see `WORKTREES.md`)
- ❌ **Do not skip unit tests** after changes to `translator.py`
- ❌ **Do not hardcode API keys** in `litellm-config.yaml` — use `os.environ/CLIPROXY_API_KEY`
- ❌ **Do not set `CACHE_ENABLED=true`** in production — LiteLLM's auth-aware cache is preferred
- ❌ **Do not force-push** to `main`
- ❌ **Do not merge with uncommitted changes** in the worktree
- ❌ **Do not touch `~/.cli-proxy-api/` directly** — dev stacks seed their own isolated auth volume

---

## Linting

```bash
pip install ruff                                                   # one-time install
ruff check services/translator/translator.py                      # lint
ruff format --check services/translator/translator.py             # format check
bash -n cliproxy-setup.sh                                         # shell syntax
python3 -c "import yaml; yaml.safe_load(open('litellm-config.yaml'))"  # YAML
```

Pre-commit hooks (install once: `pip install pre-commit && pre-commit install`)
cover ruff, YAML validation, and hardcoded API key detection automatically.

Optional pre-push hook (Gate A fast checks): `git config core.hooksPath .githooks`
runs `make lint && make test-unit` before each push.

CI (GitHub Actions `.github/workflows/ci.yml`) runs Gate A + B on every push and PR to `main`:
`lint-and-syntax`, `unit-tests`, `multi-repo-isolation`, `mock-integration`.
Gate C (`real-provider-e2e`) runs on label `run-e2e`, manual dispatch, or nightly schedule — not required to merge.

See `TESTING_AND_PROMOTION_POLICY.md` and `REPO_IMPROVEMENT_APPENDIX.md` for full gate mapping.

---

## Regression prevention guardrails

| Risk | Guard |
|------|-------|
| Broken YAML config | Pre-commit hook + CI `lint-and-syntax` |
| Hardcoded secrets committed | `.githooks/prevent-hardcoded-keys.sh` |
| Lint regressions | `ruff` in CI on every push |
| Translator logic broken | Unit tests (`test_translator*.py`) in CI |
| Multi-repo isolation broken | `multi-repo-isolation` job in CI |
| Wire-format / routing broken | `mock-integration` job (0 skips) |
| Real provider regressions | Gate C: `run-e2e` label + nightly schedule |
| Live models stop responding | Gate D: 3 model smokes on stable after merge |
| Stable stack taken down | Worktree isolation (step 1) |
| Direct push bypasses review | Branch protection + PR requirement |
| Image version drift | Pinned in docker-compose files; upgrade via PR + test |
| Cross-user cache hits | `CACHE_ENABLED=false` default in translator.py |
| Two agents on same slot | Slot registry in claim comments; `./dev-env.sh list` |

---

## Architecture (brief)

```
Client → translator:4000 → litellm:4000 (internal) → cliproxy:8317
                                                         ├── Anthropic (Claude OAuth)
                                                         ├── OpenAI (Codex OAuth)
                                                         ├── Antigravity (Gemini OAuth)
                                                         ├── xAI (Grok OAuth)
                                                         └── Moonshot (Kimi OAuth)
```

The `translator` is the real entry point. It handles format translation
(Responses API → Chat Completions, Gemini CLI format, Claude Messages API)
and adds the `AI-Gateway:` model prefix. See `CLAUDE.md` for full detail.
