# AI Gateway — Agent Instructions

These instructions apply to **any AI coding agent** working in this repo
(Claude Code, Cursor Agent, Codex, Amp, or similar). For deep-dive detail
on architecture and commands, see `CLAUDE.md`. For operational procedures,
see `RUNBOOK.md`.

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
# Always branch off dev, not main
git checkout dev
git worktree add ../ai-gateway-<feature> -b feat/<feature>
ln -s /home/dev/repos/ai-gateway/.env /home/dev/repos/ai-gateway-<feature>/.env
cd /home/dev/repos/ai-gateway-<feature>
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

### Step 4 — Test after each significant change

Run unit tests inside the dev translator container:

```bash
docker exec aidev1-translator-1 pytest test_translator.py -v
```

All 41 tests must pass before continuing. Fix failures before moving on.

### Step 5 — Commit checkpoints

Commit before risky changes and at logical stopping points — not just at the end.
This keeps session history recoverable.

```bash
git add -p
git commit -m "feat(scope): short imperative description"
```

See [Commit message format](#commit-message-format) below.

### Step 6 — End-of-session integration tests

When your feature is complete, run the full integration suite against the dev slot:

```bash
# Integration tests (requires live dev stack)
./dev-env.sh test 1

# Provider auth and service health
./cliproxy-setup.sh health
```

Resolve all failures before merging. Do not proceed with a broken dev stack.

### Step 7 — Merge to dev

```bash
cd /home/dev/repos/ai-gateway
git checkout dev
git merge feat/<feature> --no-ff -m "feat(scope): description"
docker compose exec translator pytest test_translator.py -v   # must still pass
git push origin dev
```

### Step 8 — Open a PR to main (required)

**Never push directly to main.** Open a PR so CI runs and leaves a review trail.

```bash
gh pr create --base main --head dev \
  --title "feat(scope): description" \
  --body "$(cat <<'EOF'
## Summary
- What changed and why

## Test plan
- [ ] Unit tests pass (41/41)
- [ ] Integration tests pass on dev slot
- [ ] ./cliproxy-setup.sh test claude-sonnet-4-6
- [ ] ./cliproxy-setup.sh test gemini-3-flash
- [ ] ./cliproxy-setup.sh test gpt-5-4

🤖 Generated with Claude Code
EOF
)"
```

Wait for CI to pass (GitHub Actions: lint + unit tests). Then merge:

```bash
gh pr merge --merge   # or --squash for a single clean commit
git pull origin main
```

### Step 9 — E2E test main after merge

```bash
./cliproxy-setup.sh test claude-sonnet-4-6
./cliproxy-setup.sh test gemini-3-flash
./cliproxy-setup.sh test gpt-5-4
./cliproxy-setup.sh health
```

All three model tests must return a valid response. If any fail, investigate and
fix before the session ends.

### Step 10 — Clean up

```bash
./dev-env.sh stop 1
cd /home/dev/repos/ai-gateway
git worktree remove ../ai-gateway-<feature>
git branch -d feat/<feature>
```

---

## Test commands reference

| Scope | Command | When |
|-------|---------|------|
| Unit tests | `docker exec aidev1-translator-1 pytest test_translator.py -v` | After each significant change |
| Integration (dev slot) | `./dev-env.sh test 1` | End of session, before merging |
| Single model E2E | `./cliproxy-setup.sh test <model>` | After merging to dev and after main |
| Health check | `./cliproxy-setup.sh health` | Any time; always after merging |
| YAML validation | `python3 -c "import yaml; yaml.safe_load(open('litellm-config.yaml'))"` | After editing litellm-config.yaml |

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
- ❌ **Do not skip unit tests** after changes to `translator.py`
- ❌ **Do not hardcode API keys** in `litellm-config.yaml` — use `os.environ/CLIPROXY_API_KEY`
- ❌ **Do not set `CACHE_ENABLED=true`** in production — LiteLLM's auth-aware cache is preferred
- ❌ **Do not force-push** to `main` or `dev`
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

CI (GitHub Actions `.github/workflows/ci.yml`) runs lint/format checks, shell syntax verification, container-native unit tests, multi-repo isolation tests, and E2E integration tests against a live stack on every push and PR. PRs to `main` must pass CI before merging.

---

## Regression prevention guardrails

| Risk | Guard |
|------|-------|
| Broken YAML config | Pre-commit hook + CI `yaml-validate` job |
| Hardcoded secrets committed | `.githooks/prevent-hardcoded-keys.sh` |
| Lint regressions | `ruff` in CI on every push |
| Translator logic broken | 41 unit tests in CI |
| Multi-repo isolation broken | direnv + isolation test suite in CI |
| Gateway E2E flow broken | E2E integration tests against live stack in CI |
| Live models stop responding | E2E test 3 models before finishing (step 9) |
| Stable stack taken down | Worktree isolation (step 1) |
| Direct push bypasses review | Branch protection + PR requirement (step 8) |
| Image version drift | Pinned in docker-compose files; upgrade via PR + test |
| Cross-user cache hits | `CACHE_ENABLED=false` default in translator.py |

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
