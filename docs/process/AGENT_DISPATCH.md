# Agent Dispatch Prompt — AI Gateway

> Generic, portable version of this prompt lives at
> `packages/repo-improvement-kit/AGENT_DISPATCH.template.md`. This file is the
> AI Gateway-specific instantiation: repo slug, local path, dev-slot model, test
> commands, and current issue priorities. Process rules are defined in
> `docs/process/REPO_IMPROVEMENT_WORKFLOW.md`; environment/test commands are
> defined in `docs/process/REPO_IMPROVEMENT_APPENDIX.md`.

Copy and paste this prompt to any AI agent (Claude Code, Cursor Agent, Codex, Amp, etc.)
to have it pick up and work an open issue from this repo without conflicting with other agents.

---

## Prompt (copy everything below this line)

---

You are an AI coding agent working on the `echoares-lab/ai-gateway` repository at `/home/dev/repos/ai-gateway`.

Read `AGENTS.md` and `CLAUDE.md` in that repo before doing anything else. They contain required workflow rules you must follow.

Your job is to:
1. Find an open, unclaimed issue to work
2. Claim it safely so no other agent takes it
3. Implement, test, and submit a pull request
4. Auto-merge the PR if all checks pass

---

## Step 1 — Find a claimable issue

Run:
```bash
gh issue list --repo echoares-lab/ai-gateway \
  --state open \
  --label "status:ready" \
  --json number,title,labels,assignees \
  --jq '.[] | select(.assignees | length == 0)'
```

**Rules for choosing an issue:**
- Pick the **highest-priority, lowest-numbered** issue that has no assignee
- Do NOT pick an issue with `status:claimed` or any assignee already set
- Do NOT pick an epic issue (title starts with "Roadmap Epic:") unless you are planning to work one of its specific sub-issues instead — epics are coordination parents, not direct work units
- If the issue body says `Depends on: #N`, check that #N is already closed before claiming
- Roadmap epics (#29–#38) each have sub-issues (#39–#43 for the MCP epic) — prefer sub-issues over parent epics
- If all `priority:high` issues are claimed or blocked, take the next available `priority:medium`

**Priority order (refer to `docs/ROADMAP.md` for current approved items):**

---

## Step 2 — Claim the issue (do this before writing any code)

```bash
# Replace NNN with the issue number you chose
ISSUE=NNN
SHORT_NAME=<short-name>
SLOT=<slot-number>

# Unique per agent session. Required because multiple agents may share one GitHub account.
CLAIM_ID="codex-${SHORT_NAME}-$(date -u +%Y%m%dT%H%M%SZ)"

# Assign yourself
gh issue edit $ISSUE --repo echoares-lab/ai-gateway --add-assignee "@me"

# Post a claim comment with your branch/slot info
gh issue comment "$ISSUE" --repo echoares-lab/ai-gateway --body "$(cat <<EOF
Starting work on this issue.
Claim-ID: $CLAIM_ID
Claiming: #$ISSUE
Branch: feat/$SHORT_NAME
Worktree: /home/dev/worktrees/ai-gateway-$SHORT_NAME
Slot: $SLOT
Scope: <one-line description of what you will change>
EOF
)"

# Update the status label
gh issue edit $ISSUE --repo echoares-lab/ai-gateway \
  --remove-label "status:ready" \
  --add-label "status:claimed"
```

**If another agent claims the issue between steps 1 and 2, move to the next available issue.**
If you see an existing claim comment, compare its `Claim-ID`, branch, worktree,
and last update before continuing. Do not continue someone else's claim just
because it uses the same GitHub account.

---

## Step 3 — Set up your isolated worktree and dev stack

**Branch choice (read issue `Depends on:` first):**

| Dependency state | Branch from | PR base |
|------------------|-------------|---------|
| None, or dependency merged to `main` | `main` | `main` |
| Dependency PR open and CI-green | `feat/<dep-short-name>` | `feat/<dep-short-name>` (stacked) |

Poll before setup:

```bash
gh issue view <dep-issue> --json state,closed
gh pr view <dep-pr> --json state,mergedAt,statusCheckRollup
```

```bash
cd /home/dev/repos/ai-gateway

# Check which dev slots are free — pick an unclaimed slot
./dev-env.sh list

# Create a worktree (outside repos/ — see docs/process/WORKTREES.md)
mkdir -p /home/dev/worktrees
git fetch origin

# Independent work (most issues):
git checkout main
git pull origin main
git worktree add /home/dev/worktrees/ai-gateway-<short-name> -b feat/<short-name>

# Stacked work (only when dependency PR is open and stable):
# git worktree add /home/dev/worktrees/ai-gateway-<short-name> -b feat/<short-name> feat/<dep-short-name>

ln -s /home/dev/repos/ai-gateway/.env /home/dev/worktrees/ai-gateway-<short-name>/.env
cd /home/dev/worktrees/ai-gateway-<short-name>

# Start an isolated dev stack on the slot you declared in the claim comment
./dev-env.sh start <slot>
```

**Never edit files in `/home/dev/repos/ai-gateway` directly — that is the main checkout, kept clean for pulls/Gate D.**
**Never use slot 0 — that is reserved for the optional local stack on port 4000 (not production; production is k8s).**
**One issue = one agent = one slot = one worktree.**

---

## Step 4 — Implement the issue

Read the full issue body carefully. Follow the **Actions** and satisfy the **Acceptance criteria**.

During implementation:
- Make changes — the gateway-engine hot-reloads in ~1s, litellm-config.yaml hot-reloads in ~10s
- After each significant change, run unit tests:
  ```bash
  docker exec aidev<slot>-gateway-engine-1 pytest test_gateway_engine*.py -v
  ```
- For gateway/wire-format changes, also run the fast mock integration tier:
  ```bash
  make test-mock
  # or the full local fast tier:
  make test-fast
  ```
  Gate B is in-memory ASGI integration (`tests/integration/ -m mock`), requires no OAuth, and must have **0 skips**.
- All gateway-engine unit tests must pass before continuing
- Commit often with conventional messages:
  ```bash
  git add -p
  git commit -m "feat(scope): description"
  ```

**Do NOT hardcode API keys.** Use `os.environ/KEY_NAME` in litellm-config.yaml and env vars elsewhere.

---

## Step 5 — End-of-session testing

When implementation is complete:

```bash
# Fast mock integration tier (required for gateway-engine/wire-format/config routing changes)
make test-mock
# Prefer the full local fast tier before opening a PR:
make test-fast

# Real-provider integration against your dev slot (run when the change touches provider auth,
# CLIProxy behavior, model availability, or before labeling the PR `run-e2e`)
./dev-env.sh test <slot>

# Health check
./cliproxy-setup.sh health

# Update issue status
gh issue edit $ISSUE --repo echoares-lab/ai-gateway \
  --remove-label "status:claimed" \
  --add-label "status:in-review"
```

All tests must pass. Fix any failures before proceeding.

---

## Step 6 — Rebase (if needed) and open a PR

**If your issue depended on another PR that has since merged**, rebase onto `main` before opening or updating the PR:

```bash
cd /home/dev/worktrees/ai-gateway-<short-name>
git fetch origin
git rebase origin/main
# resolve conflicts → git add … → git rebase --continue
make test-fast
git push --force-with-lease origin feat/<short-name>
```

**Never push directly to main.** Open a PR so CI runs and leaves a review trail.
Use `--base main` unless you are intentionally stacking on an open dependency branch.

```bash
gh pr create \
  --repo echoares-lab/ai-gateway \
  --base main \
  --head feat/<short-name> \
  --title "feat(scope): description (#NNN)" \
  --body "$(cat <<'EOF'
## Summary
- What changed and why

## Linked issues
- Fixes #NNN

## Test plan
- [ ] Gateway Engine unit tests pass (41/41)
- [ ] Mock integration tier passes with 0 skips (`make test-mock`)
- [ ] Real-provider integration / `run-e2e` label used only when needed
- [ ] Health check passes
- [ ] Claude E2E: ./cliproxy-setup.sh test claude-sonnet-4-6 (if real E2E needed)
- [ ] Gemini E2E: ./cliproxy-setup.sh test gemini-3-flash (if real E2E needed)
- [ ] GPT E2E: ./cliproxy-setup.sh test gpt-5-4 (if real E2E needed)
- [ ] CI fast-tier checks passed

## Risk / rollback
- Risk level: low / medium / high
- Rollback plan: revert commit or re-run sync-models

## Workflow checklist
- [x] Issue was approved before implementation
- [x] Issue was claimed with a start-work comment
- [x] Claim comment includes unique Claim-ID: `<claim-id>`
- [x] Dependencies were handled
- [x] Manual verification recorded above
EOF
)"
```

---

## Step 7 — Wait for CI and merge

**Before merge:** If `main` advanced since your last green CI run (e.g. a dependency PR just merged), rebase again:

```bash
cd /home/dev/worktrees/ai-gateway-<short-name>
git fetch origin && git rebase origin/main
make test-fast
git push --force-with-lease origin feat/<short-name>
```

```bash
PR_NUMBER=$(gh pr list --repo echoares-lab/ai-gateway --head feat/<short-name> --json number --jq '.[0].number')

# Enable auto-merge (merges automatically once required fast-tier checks pass)
gh pr merge $PR_NUMBER \
  --repo echoares-lab/ai-gateway \
  --merge \
  --auto

# Optional: trigger full real-provider E2E when the change touches provider auth,
# CLIProxy behavior, model availability, or other upstream-dependent behavior.
# This job is intentionally not a required check.
# gh pr edit $PR_NUMBER --repo echoares-lab/ai-gateway --add-label run-e2e

# Watch CI status
gh pr checks $PR_NUMBER --repo echoares-lab/ai-gateway --watch
```

**If auto-merge is disabled or does not trigger**, merge manually once checks are green:

```bash
gh pr merge $PR_NUMBER --repo echoares-lab/ai-gateway --merge
```

**If CI fails:**
1. Read the failure output
2. Fix the issue in your worktree
3. Push the fix to your PR branch
4. CI will re-run automatically
5. Auto-merge (or manual merge) proceeds once all required fast-tier checks are green

**If CI `mock-integration` fails on infra** but local Gate B passes, run `make test-mock` in your worktree, paste the result in the PR comment, and re-run failed jobs or push an empty commit to retry.

**Required fast-tier CI checks that must pass:**
- `lint-and-syntax` — ruff check + format, shell syntax, YAML syntax, no hardcoded keys
- `unit-tests` — gateway-engine unit tests
- `multi-repo-isolation` — environment isolation checks
- `mock-integration` — gateway-engine + LiteLLM + mock upstream integration tests (0 skips)

**Gated CI check:**
- `real-provider-e2e` — runs only on `workflow_dispatch` or PR label `run-e2e`; not required by default

---

## Step 8 — Gate D: post-merge verification against k8s production

Real production runs on k3s-01, not this host. Gate D is fully automated:
`.github/workflows/production-health-heartbeat.yml` runs on every push to `main`, hitting
`https://ai.plexplease.com` directly (health check + models list + a smoke completion per
model). No manual command or local stack is needed. Check the workflow run/job summary for
the merge commit and record the result in closeout.

Still pull `main` into the main checkout to keep it current for the next session:

```bash
cd /home/dev/repos/ai-gateway
git status    # must be clean — stash or discard any local edits first
git pull origin main
```

**Do not leave uncommitted changes in the main checkout** — they block this `git pull`.

---

## Step 9 — Close the issue and clean up (after merge only)

Run this **only after** the PR is merged and Gate D passes. Keep the worktree and dev
stack alive while the PR is open for fixes and rebase.

```bash
# Post completion summary on the issue
gh issue comment $ISSUE --repo echoares-lab/ai-gateway --body "$(cat <<'EOF'
✅ DONE

- PR: #<pr-number>
- Merge commit: <sha>
- Gates run:
  - Gate A: lint-and-syntax, unit-tests (test_gateway_engine*.py)
  - Gate B: mock-integration (0 skips)
  - Gate C: real-provider-e2e (if high-risk / run-e2e label)
  - Gate D: automated `production-health-heartbeat` workflow against k8s prod
- Verified on: main (production)
- Cleanup: slot <slot> stopped, worktree removed, branch deleted
- Follow-up issues: none / #NNN
EOF
)"

# Close the issue
gh issue close $ISSUE --repo echoares-lab/ai-gateway

# Clean up dev stack and worktree
./dev-env.sh stop <slot>
cd /home/dev/repos/ai-gateway
git worktree remove /home/dev/worktrees/ai-gateway-<short-name>
git branch -d feat/<short-name>

# Verify cleanup
git worktree list
./dev-env.sh list
```

**If `git worktree remove` fails:** stash or commit remaining changes in the feature
worktree, ensure `./dev-env.sh stop <slot>` succeeded, retry removal, then `git worktree prune`.

**Parent / coordinator agents:** Confirm subagent cleanup (`git worktree list`, `./dev-env.sh list`)
before closing epics or ending a multi-agent session.

---

## Quick reference — test commands

| Command | When |
|---------|------|
| `docker exec aidev<slot>-gateway-engine-1 pytest test_gateway_engine*.py -v` | Gate A — after every significant change |
| `make test-fast` | Gate A + B — local equivalent of required CI fast tier |
| `make test-mock` | Gate B only — in-memory ASGI, 0 skips |
| `./dev-env.sh test <slot>` | Gate C — real-provider integration when broader coverage needed |
| `gh pr edit <pr> --add-label run-e2e` | Trigger Gate C in CI (`real-provider-e2e`) |
| `./cliproxy-setup.sh health` | Optional manual check of the local stack (not part of Gate D) |
| (none — Gate D is automated) | Gate D — post-merge model smoke against k8s prod |

---

## What NOT to do

- ❌ Do NOT push directly to `main`
- ❌ Do NOT edit files in the main `/home/dev/repos/ai-gateway` worktree during development
- ❌ Do NOT create worktrees under `/home/dev/repos/` or inside the repo (`.claude/`, `.cursor/`, etc.) — use `/home/dev/worktrees/ai-gateway-<name>`
- ❌ Do NOT claim an issue that already has an assignee
- ❌ Do NOT skip unit tests
- ❌ Do NOT hardcode API keys anywhere
- ❌ Do NOT close an issue before the PR is merged to main and E2E passes
- ❌ Do NOT work on a parent epic issue — only concrete sub-issues are claimable work units

---

## Conflict avoidance and multi-agent rules

If two agents are running simultaneously:
- Each agent works a **different issue** (enforced by the assignee check in Step 2)
- Each agent uses a **different dev slot** (check `./dev-env.sh list` before starting; never slot 0)
- Each agent uses a **different worktree** (different directory and branch name)
- Each claim uses a **unique `Claim-ID`** per session (not just per GitHub account)
- Issues touching the same hotspot (`main.py`, `litellm-config.yaml`, etc.) are **serialized** — use `Depends on:` or stacked PRs + rebase after the first merges
- Poll dependency state with `gh issue view` / `gh pr view` before claiming or implementing
- After a dependency merges: `git fetch origin && git rebase origin/main`, resolve conflicts, `make test-fast`, `git push --force-with-lease`
- CI `mock-integration` infra flakes: confirm with local `make test-mock` before retrying merge
- Auto-merge may be off — use `gh pr merge <num> --merge` when `--auto` does not queue
- Main checkout stays **read-only** for feature work; keep it clean for the post-merge `git pull`

The optional local stack on port 4000 is never touched by any agent — it isn't production and isn't part of any required workflow.
