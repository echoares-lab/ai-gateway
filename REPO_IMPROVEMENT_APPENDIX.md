# Repo Improvement Appendix: AI Gateway

Repo-specific operating details for `REPO_IMPROVEMENT_WORKFLOW.md`.
Gate definitions: `TESTING_AND_PROMOTION_POLICY.md`. Testing guide: `docs/TESTING.md`. CI runner: `docs/CI_SELF_HOSTED.md`.

## Branch and worktree policy

```text
main -> feat/* worktree/branch -> PR -> main
```

- Create feature worktrees from `main` only (no long-lived `dev` branch).
- **Worktree location:** `/home/dev/worktrees/ai-gateway-<feature>` — see `WORKTREES.md`.
- Do **not** put worktrees under `/home/dev/repos/` (siblings of stable) or inside the repo (`.claude/`, `.cursor/`, etc.).
- Do not edit the stable worktree at `/home/dev/repos/ai-gateway` for feature work.
- Keep slot 0 reserved for the stable stack.
- Use a separate dev stack slot for work that needs live-service validation.
- One active claim = one worktree + one branch + one slot (declare in claim comment).

## Environment strategy

- Stable stack: port 4000 (slot 0).
- Dev stacks: `./dev-env.sh start <slot>` (slots 1, 2, 3, …).
- Mock stack (Gate B): `./dev-env.sh start-mock 9` → gateway-engine on :4090.
- Slot 1 maps gateway-engine to port 4010; slot 2 maps gateway-engine to port 4020.
- Gateway Engine changes hot-reload through uvicorn.
- `litellm-config.yaml` changes are picked up by the LiteLLM reloader.

## Test gates

| Gate | Purpose | Local command | CI job |
|------|---------|---------------|--------|
| **A** | Lint, schema, unit | `make lint` / `make test-unit` | `lint-and-syntax`, `unit-tests`, `build-gateway-engine`, path-filtered service tests |
| **B** | Mock integration (0 skips) | `make test-mock` | `mock-integration` |
| **C** | Real providers (smoke) | `make test-e2e` or PR label `run-e2e` | `real-provider-e2e` (**required on hotspot paths**) |
| **D** | Post-merge stable | `./cliproxy-setup.sh health` + model smokes on :4000 | `post-merge-gate-d` (advisory) |

**Agent loop (before push):** `make test-fast` (Gate A + B locally, ~5 min). Does **not** run `multi-repo-isolation` — run `bash tests/test-multi-repo-isolation.sh` when touching isolation scripts.

**Optional pre-push hook:** `make lint && make test-unit` (see `.githooks/pre-push`).

### Risk tiers (PR checklist)

| Risk | Gate A | Gate B | Gate C | Gate D |
|------|--------|--------|--------|--------|
| Low (docs, templates) | yes | optional | no | no |
| Medium (gateway-engine logic, tests) | yes | yes | no | no |
| High (auth, litellm-config, compose, cliproxy) | yes | yes | **required on hotspot paths** | post-merge on stable |

### CI check tiers (Required vs Advisory)

| Tier | Jobs | Blocks merge? |
|------|------|---------------|
| **Required — Fast (A)** | `lint-and-syntax`, `unit-tests`, `build-gateway-engine` | Yes, every PR |
| **Required — Conditional** | `mock-integration`, `multi-repo-isolation`, `credential-prober`, `policy-engine-tests` | Yes, when paths match (skipped = pass) |
| **Required — Hotspot (C)** | `real-provider-e2e` | Yes, when hotspot paths change |
| **Advisory** | `nightly-integration`, `hotspot-e2e-reminder`, `post-merge-gate-d` | No |

### Docs-only PRs

When only docs/templates change, conditional jobs (`mock-integration`, etc.) **skip**. GitHub treats skipped required checks as passing. Optional `docs-only` label for maintainer audit.

### CI job → gate mapping (branch protection)

Required on `main` PRs:
- `lint-and-syntax`, `unit-tests`, `build-gateway-engine` → Gate A
- `multi-repo-isolation` → Gate A (isolation paths)
- `mock-integration` → Gate B (runtime paths)
- `real-provider-e2e` → Gate C (**hotspot paths**; skipped when not applicable)

Path-filtered (required when triggered):
- `credential-prober`, `policy-engine-tests` → Gate A

Advisory:
- `nightly-integration`, `post-merge-gate-d` → Gate C/D signal

## Required checks (copy-paste)

- Gateway Engine unit tests: `docker run --rm ai-gateway-engine-test:latest pytest test_gateway-engine*.py -n auto -v`
- Policy-engine unit tests: `PYTHONPATH=services/policy-engine pytest services/policy-engine/test_*.py -v`
- Mock integration: `make test-mock`
- Multi-repo isolation: `bash tests/test-multi-repo-isolation.sh` (CI only; needs direnv setup)
- YAML validation: `python3 -c "import yaml; yaml.safe_load(open('litellm-config.yaml'))"`
- Shell syntax for changed scripts: `bash -n <script>`

## Manual E2E verification (Gate C + D)

**Gate C (pre-merge, hotspot / high-risk):**
- Auto-triggered on hotspot paths (see below)
- PR label `run-e2e` re-triggers CI `real-provider-e2e`
- Local: `./dev-env.sh test <slot>` or `make test-e2e`

**Gate D (post-merge on stable, port 4000):**
- `./cliproxy-setup.sh health`
- `./cliproxy-setup.sh test claude-sonnet-4-6`
- `./cliproxy-setup.sh test gemini-3-flash`
- `./cliproxy-setup.sh test gpt-5-4`

## Hotspot files and areas

Gate C **required** when PR touches:
- `services/gateway-engine/**` (includes `main.py`)
- `litellm-config.yaml`
- `docker-compose*.yml`, `Dockerfile*`
- `cliproxy-setup.sh`, `dev-env.sh`

## Versioning and promotion

- Production stack: `docker-compose.yml` on `main` (stable worktree, slot 0).
- Dev stacks: `docker-compose.dev.yml` via `./dev-env.sh`.
- Pin cliproxy fork image by digest when bumping; record in PR operational notes.
- Tag `main` at production milestones; closeout comment lists merge SHA and gates run.

## Useful commands

- `./dev-env.sh list` — show running slots (check before claiming a slot)
- `./dev-env.sh start <slot>` / `./dev-env.sh stop <slot>`
- `./dev-env.sh start-mock 9` / `./dev-env.sh test-mock 9` / `./dev-env.sh stop-mock 9`
- `make test-fast` — local Gate A + B
- `make test-e2e` — local Gate C smoke
- `./cliproxy-setup.sh quota-summary`
- `./cliproxy-setup.sh sync-models`

## Slot registry

Record active slots in claim comments. Before starting a stack, run `./dev-env.sh list`.
Do not share a slot between concurrent claims without an explicit handoff in the issue thread.

| Slot | Purpose |
|------|---------|
| 0 | Stable production-like stack (:4000) — **never use for feature work** |
| 1–8 | Real OAuth dev stacks (Gate C) |
| 9 | Mock stack (Gate B) — default for `make test-mock` |

## Parallel agents: rebase and stacking

| Situation | Branch from | PR base |
|-----------|-------------|---------|
| No dependency / dependency merged | `main` | `main` |
| Dependency PR open and stable | `feat/<dep>` | `feat/<dep>` |

After dependency merges:

```bash
cd /home/dev/worktrees/ai-gateway-<feature>
git fetch origin && git rebase origin/main
make test-fast
git push --force-with-lease origin feat/<feature>
```

Poll dependencies: `gh issue view <n> --json state,closed` and `gh pr view <n> --json state,mergedAt`.

Hotspot files (`services/gateway-engine/**`, `litellm-config.yaml`, compose files) require serialized
issues or explicit stack order — see `REPO_IMPROVEMENT_WORKFLOW.md` §9.

## Worktree cleanup (post-merge)

Only after PR merge + Gate D:

```bash
./dev-env.sh stop <slot>
cd /home/dev/repos/ai-gateway
git status    # stable must be clean before Gate D pull
git pull origin main
git worktree remove /home/dev/worktrees/ai-gateway-<feature>
git branch -d feat/<feature>
git worktree list
./dev-env.sh list
```

On removal failure: stash/commit in feature worktree, stop stack, retry, `git worktree prune`.
Coordinator agents verify cleanup before closing parent epics.

## Mock data seeding (Gate B / dev stacks)

Dev and mock stacks avoid ~15 min LiteLLM `proxy_extras` migrations on fresh Postgres volumes:

1. **`init-db-bootstrap.sql`** — creates `litellm` / `langfuse` databases only (no tables).
2. **`db/seed-litellm-mock.sql`** — pre-migrated LiteLLM schema + `_prisma_migrations` rows (~150 KB).
   Loaded at first volume init (`docker-entrypoint-initdb.d/02`) or via `scripts/load-mock-data.sh`
   when reusing an older empty volume.
3. **`db/apply-migrations.sh`** — gateway tables (`credential_inventory`, policy profiles).
4. **`LITELLM_MIGRATIONS=None`** — LiteLLM skips Prisma migrations (schema already present).

Regenerate seed after LiteLLM image bump: `scripts/generate-litellm-mock-seed.sh` (requires stable
`ai-postgres-1` with migrations applied). CI `mock-integration` uses `CI_MOCK_FRESH_DB=1` on PRs
to drop the `aidevmock` Postgres volume (`scripts/ci-free-mock-host-ports.sh`).

**CI flake:** If `mock-integration` fails in CI but `make test-mock` passes locally, note it in the PR and retry.

**Manual merge:** If `gh pr merge --auto` is unavailable, use `gh pr merge <num> --merge` after green checks.
