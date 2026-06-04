# Repo Improvement Appendix: AI Gateway

Repo-specific operating details for `REPO_IMPROVEMENT_WORKFLOW.md`.
Gate definitions: `TESTING_AND_PROMOTION_POLICY.md`.

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
- Mock stack (Gate B): `./dev-env.sh start-mock 9` → translator on :4090.
- Slot 1 maps translator to port 4010; slot 2 maps translator to port 4020.
- Translator changes hot-reload through uvicorn.
- `litellm-config.yaml` changes are picked up by the LiteLLM reloader.

## Test gates

| Gate | Purpose | Local command | CI job |
|------|---------|---------------|--------|
| **A** | Lint, schema, unit | `make lint` / `make test-unit` | `lint-and-syntax`, `unit-tests`, `credential-prober` |
| **B** | Mock integration (0 skips) | `make test-mock` | `mock-integration` |
| **C** | Real providers (smoke) | `make test-e2e` or PR label `run-e2e` | `real-provider-e2e` (not required) |
| **D** | Post-merge stable | `./cliproxy-setup.sh health` + model smokes on :4000 | n/a (manual) |

**Agent loop (before push):** `make test-fast` (Gate A + B locally, ~5 min).

**Optional pre-push hook:** `make lint && make test-unit` (see `.githooks/pre-push`).

### Risk tiers (PR checklist)

| Risk | Gate A | Gate B | Gate C | Gate D |
|------|--------|--------|--------|--------|
| Low (docs, templates) | yes | optional | no | no |
| Medium (translator logic, tests) | yes | yes | no | no |
| High (auth, litellm-config, compose, cliproxy) | yes | yes | smoke (`run-e2e` label) | post-merge on stable |

### CI job → gate mapping (branch protection)

Required on `main` PRs:
- `lint-and-syntax` → Gate A
- `unit-tests` → Gate A
- `multi-repo-isolation` → Gate A (environment isolation)
- `mock-integration` → Gate B
- `credential-prober` → Gate A (when `services/credential-prober/` changes)

Not required:
- `real-provider-e2e` → Gate C
- `nightly-integration` → Gate C (scheduled, report-only)

## Required checks (copy-paste)

- Translator unit tests: `docker run --rm ai-translator-test:latest pytest test_translator*.py -v`
- Mock integration: `make test-mock`
- Multi-repo isolation: `bash tests/test-multi-repo-isolation.sh` (CI only; needs direnv setup)
- YAML validation: `python3 -c "import yaml; yaml.safe_load(open('litellm-config.yaml'))"`
- Shell syntax for changed scripts: `bash -n <script>`

## Manual E2E verification (Gate C + D)

**Gate C (pre-merge, high-risk):**
- `./dev-env.sh test <slot>` or `make test-e2e`
- PR label `run-e2e` triggers CI `real-provider-e2e`

**Gate D (post-merge on stable, port 4000):**
- `./cliproxy-setup.sh health`
- `./cliproxy-setup.sh test claude-sonnet-4-6`
- `./cliproxy-setup.sh test gemini-3-flash`
- `./cliproxy-setup.sh test gpt-5-4`

## Hotspot files and areas

Gate C recommended when PR touches:
- `services/translator/translator.py`
- `litellm-config.yaml`
- `docker-compose.yml`, `docker-compose.dev.yml`, `Dockerfile.cliproxy`
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
