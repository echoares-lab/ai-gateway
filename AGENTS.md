# AI Gateway — Agent Instructions

See the [API Documentation System](docs/API_DOCUMENTATION.md) for technical endpoint references.
**Mandatory**: Any new API endpoints created or discovered must be documented in `docs/openapi/` and registered in the system.
See [`docs/process/REPO_IMPROVEMENT_APPENDIX.md`](docs/process/REPO_IMPROVEMENT_APPENDIX.md) and [`docs/TESTING.md`](docs/TESTING.md).

These instructions apply to **any AI coding agent** working in this repo
(Claude Code, Cursor Agent, Codex, Amp, or similar). For deep-dive detail
on architecture and commands, see `CLAUDE.md`. For operational procedures,
see [`docs/ops/RUNBOOK.md`](docs/ops/RUNBOOK.md) (root stub: `RUNBOOK.md`).

Repo improvement and PR processing are governed by:
- [`docs/process/REPO_IMPROVEMENT_WORKFLOW.md`](docs/process/REPO_IMPROVEMENT_WORKFLOW.md) — process rules (discovery, approval, claim, PR, merge, closeout).
- [`docs/process/TESTING_AND_PROMOTION_POLICY.md`](docs/process/TESTING_AND_PROMOTION_POLICY.md) — gate definitions (A/B/C/D), risk tiers, parallel-agent isolation, and the new [Epic-Based Development and Release Policy](#epic-based-development-and-release-policy).
- [`docs/process/REPO_IMPROVEMENT_APPENDIX.md`](docs/process/REPO_IMPROVEMENT_APPENDIX.md) — this repo's branch policy, environment slots, and test commands.
- [`docs/process/AGENT_DISPATCH.md`](docs/process/AGENT_DISPATCH.md) — the copy-paste prompt agents run to claim an issue and ship it.
- [`packages/repo-improvement-kit/`](packages/repo-improvement-kit/) — portable source for the above; see its `README.md` for deployment.

**Roadmap vs candidates:** Claim work only from approved items in
[`docs/ROADMAP.md`](docs/ROADMAP.md) (and their ready GitHub child issues).
[`docs/FEATURE_CANDIDATES.md`](docs/FEATURE_CANDIDATES.md) is an unapproved
inventory — do not claim or implement from it until an item is promoted into
the roadmap and atomic issues are opened.

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

Port 4000 is the optional local `docker-compose.yml` stack (not production — see
[`CLAUDE.md`](CLAUDE.md)); it isn't running by default. Dev stacks use slots (port 4010, 4020, …).

---

## Environment requirements

- `.env` must exist (copy from `.env.example`); it is gitignored — never commit it
- `~/.cliproxy/config.yaml` and `~/.cli-proxy-api/` must exist for cliproxy volume mounts
- On a remote server: open SSH port forwards before OAuth login (see [`docs/ops/RUNBOOK.md`](docs/ops/RUNBOOK.md))

---

## ⚠️ The non-negotiable rule

**Never edit files in the main checkout (`/home/dev/repos/ai-gateway`) directly.**

All development must happen in an isolated worktree with its own dev stack slot. Real
production and staging run on k3s-01, not this host — the main checkout must stay clean
because it's what Gate D (`git pull origin main`) and epic-closeout tooling operate
against, and because a dirty main checkout blocks pulling in the latest `main` for the
next session. This is enforced by convention, not by tooling — agents must follow it.

---

## Development workflow

Every session follows this sequence. Do not skip steps. This workflow is designed to align with the [Epic-Based Development and Release Policy](#epic-based-development-and-release-policy) in [`docs/process/TESTING_AND_PROMOTION_POLICY.md`](docs/process/TESTING_AND_PROMOTION_POLICY.md) and the detailed worktree instructions in [`docs/process/WORKTREES.md`](docs/process/WORKTREES.md).

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

# Start your slot (1, 2, 3, …  — slot 0 is the optional local stack, reserved)
./dev-env.sh start 1
```

Dev slots map to ports:
| Slot | gateway-engine | litellm UI | cliproxy |
|------|-----------|------------|----------|
| 1 | :4010 | :4011 | :8327 |
| 2 | :4020 | :4021 | :8337 |

### Step 3 — Make changes (hot-reload is automatic)

- `services/gateway-engine/main.py` edits → uvicorn reloads in ~1 second (no action needed)
- `Dockerfile` or pip dependency changes → `./dev-env.sh rebuild <slot>`

### Step 4 — Test after each significant change (Gate A)

Run unit tests inside the dev gateway-engine container or via Make:

```bash
docker exec aidev1-gateway-engine-1 pytest test_gateway_engine*.py -v
# or locally without a running stack:
make test-unit
```

All unit tests must pass before continuing. Fix failures before moving on.

For mock integration during development (Gate B):

```bash
make test-mock    # in-memory ASGI; no compose / no OAuth
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

For **high-risk** changes (auth, `litellm-config.yaml`, compose, cliproxy), also run Gate C
(recommended; CI does not require it to merge):

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

### Gate C (high-risk — recommended, opt-in in CI)
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
see [`docs/process/WORKTREES.md`](docs/process/WORKTREES.md) and [`docs/process/TESTING_AND_PROMOTION_POLICY.md`](docs/process/TESTING_AND_PROMOTION_POLICY.md) for detailed rebase guidance in an epic-based workflow.

Then merge:

```bash
gh pr merge --merge --auto   # or --squash; use manual --merge if auto-merge is disabled
git checkout main
git pull origin main
```

### Step 8 — Gate D: verify production after merge

Real production runs on k3s-01, not this host. The
[`production-health-heartbeat.yml`](../.github/workflows/production-health-heartbeat.yml) workflow runs
automatically on every push to `main` — it hits `https://ai.plexplease.com` (k8s
production) directly with a health check, a models-list check, and a smoke completion
per model. No manual local action is required.

Check the workflow run (or its job summary) for the commit that merged your PR; if any
check failed, investigate and fix before the session ends. Record the result in the
issue closeout.

(There is no local "stable stack" to smoke-test on this host — the optional
`docker-compose.yml` stack, if you ever bring it up manually, is not production.)

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

When multiple agents work the same repo concurrently, enforce **one issue = one agent = one slot = one worktree**. For a full explanation of the workflow, including dependencies and rebasing, refer to [`docs/process/WORKTREES.md`](docs/process/WORKTREES.md) and the [Epic-Based Development and Release Policy](#epic-based-development-and-release-policy) in [`docs/process/TESTING_AND_PROMOTION_POLICY.md`](docs/process/TESTING_AND_PROMOTION_POLICY.md).

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
| D — production smoke | Automated `production-health-heartbeat` workflow (hits k8s prod directly) | After merge to main |
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
- ❌ **Do not create feature worktrees under `/home/dev/repos/` or inside the repo** (use `/home/dev/worktrees/ai-gateway-<feature>` — see [`docs/process/WORKTREES.md`](docs/process/WORKTREES.md))
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

- **Required — Fast (A):** `lint-and-syntax`, `unit-tests` (image build is inside `unit-tests`)
- **Required — Conditional:** `mock-integration`, `multi-repo-isolation`, `credential-prober` (path-filtered)
- **Advisory (Gate C — opt-in):** `real-provider-e2e` via `run-e2e` label or `workflow_dispatch` only
- **Advisory:** `nightly-integration`, `production-health-heartbeat`, `hotspot-e2e-reminder`

See `docs/TESTING.md`, `docs/process/TESTING_AND_PROMOTION_POLICY.md`, and `docs/process/REPO_IMPROVEMENT_APPENDIX.md` for full gate mapping.

---

## Regression prevention guardrails

| Risk | Guard |
|------|-------|
| Broken YAML config | Pre-commit hook + CI `lint-and-syntax` |
| Hardcoded secrets committed | `.githooks/prevent-hardcoded-keys.sh` |
| Lint regressions | `ruff` in CI on every push |
| Gateway Engine logic broken | Unit tests (`test_gateway_engine*.py`) in CI |
| Multi-repo isolation broken | `multi-repo-isolation` job in CI |
| Wire-format / routing broken | `mock-integration` job (0 skips) |
| Real provider regressions | Gate C: opt-in via `run-e2e` label or nightly schedule |
| Post-merge production drift | Gate D: automated `production-health-heartbeat` workflow against k8s prod |
| Main checkout accidentally modified during dev | Worktree isolation (step 1) |
| Direct push bypasses review | Branch protection + PR requirement |
| Image version drift | Pinned in docker-compose files; upgrade via PR + test |
| Cross-user cache hits | `CACHE_ENABLED=false` default in gateway-engine |
| Two agents on same slot | Slot registry in claim comments; `./dev-env.sh list` |
| Orphaned worktrees / occupied slots | Post-merge cleanup checklist (Step 9); coordinator verifies `git worktree list` |
| Dirty stable worktree blocks Gate D | Never edit stable checkout; `git status` before `git pull` |
| Stacked PR conflicts after dependency merge | Rebase onto `origin/main`, `make test-fast`, `--force-with-lease` push |

---

## Kubernetes / k3s deployment

The stack also runs on the `k3s-01` cluster via ArgoCD/Kustomize. The design specs live in
this repo; the authoritative manifests live in the external `k3s-01` GitOps repo.

- `docs/CICD_PHASE2_CD_K3S.md` — **production** deployment (namespace `ai-gateway`,
  OpenBao `prod/workloads/ai-gateway/*`, ingress `gateway.infra.plexplease.com`).
- `docs/CICD_PHASE2_STAGING.md` — **staging** deployment (namespace `ai-gateway-staging`,
  OpenBao `staging/workloads/ai-gateway/*`, ingress `gateway-staging.infra.plexplease.com`,
  `litellm_staging` + `langfuse_staging` databases, `:latest`/dev images, and the
  staging → prod promotion flow).
- `scripts/ops/generate-staging-configmap.sh` renders `litellm-config.yaml` into the staging
  `litellm-config` ConfigMap (namespace `ai-gateway-staging`) and validates the embedded YAML.

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

---

## Cursor Cloud specific instructions

The Docker-based workflow above (`docker compose`, `./dev-env.sh`, `./cliproxy-setup.sh`,
worktrees/slots) is the canonical dev path, but the Cursor Cloud VM has **no Docker daemon**
and **no provider OAuth** (`~/.cli-proxy-api/`). The full stack additionally needs the external
CLIProxy fork image from Nexus (built by the `CLIProxyAPI` repo). So the Docker full stack and
**Gate C** (`make test-e2e`) are **not runnable here** — don't try to run them in the cloud VM.
(Gate D is fully automated post-merge against k8s prod and isn't manually run anywhere.)

What *does* run here is a Python-only local workflow that covers lint, both test tiers, and the
flagship `gateway-engine` service:

- The update script provisions a venv at `.venv-ci/` (Python 3.12). Prefix commands with
  `.venv-ci/bin/` (or activate it). Deps mirror `requirements/ci-runner-venv.txt` plus
  `redis[asyncio]` and `pytest-xdist`.
- **Lint (Gate A):** `.venv-ci/bin/ruff check services/gateway-engine/` and
  `.venv-ci/bin/ruff format --check services/gateway-engine/` (this is what `make lint` runs).
- **Mock integration (Gate B):** `.venv-ci/bin/python -m pytest tests/integration/ -m mock -v`
  — in-memory ASGI, no Docker/OAuth. Equivalent to `make test-mock`.
- **Unit tests (Gate A):** `make test-unit` builds a Docker image and won't work here. Run the
  same suite directly instead: `cd services/gateway-engine && /workspace/.venv-ci/bin/python -m
  pytest test_gateway_engine*.py test_token_analytics.py -n auto -v`.
- Other non-Docker `make test-fast` pieces also work via the venv:
  `scripts/policy/validate_policy_profiles.py`, `pytest tests/test_sync_models_probe_classify.py`,
  `pytest tests/test_litellm_compose_migration.py`. The `docker compose ... config` half of
  `test-compose-config` needs Docker and is skipped here.
- **Run the flagship service locally (no Docker):** from `services/gateway-engine`,
  `LITELLM_URL=<upstream> CACHE_ENABLED=false POLICY_ENGINE_ENABLED=false /workspace/.venv-ci/bin/uvicorn main:app --host 127.0.0.1 --port 4000`.
  It needs a LiteLLM-compatible upstream (real one is unavailable here; use a small mock that
  answers `GET /v1/models` and `POST /v1/chat/completions`). Redis is optional and only used when
  `CACHE_ENABLED=true`. The gateway adds the `AI-Gateway:` prefix on `/v1/models`, strips it before
  forwarding, and translates `/v1/messages` (Claude) and `/v1/responses` (Codex) to Chat Completions.
