# Agent Dispatch Prompt — AI Gateway

> Generic, portable version of this prompt lives at
> `packages/repo-improvement-kit/AGENT_DISPATCH.template.md`. This file is the
> AI Gateway-specific instantiation: repo slug, local path, dev-slot model, test
> commands, and current issue priorities. Process rules are defined in
> `REPO_IMPROVEMENT_WORKFLOW.md`; environment/test commands are defined in
> `REPO_IMPROVEMENT_APPENDIX.md`.

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

**Priority order as of this writing:**
1. `#39` — MCP architecture decision (high, no deps)
2. `#40` — MCP Phase 1 servers: filesystem, git, fetch (high, depends on #39)
3. `#42` — MCP search servers: Brave, Tavily, Exa, Serper (medium, depends on #39)
4. `#30` — Multi-tenant workspace management (high, foundational)
5. `#31` — Adaptive provider intelligence (high)
6. `#32` — Unified admin console (high, benefits from #30)
7. `#41` — MCP Phase 2 servers: GitHub, memory, sequential-thinking (medium, depends on #40)
8. `#33` — Credential pool orchestration (medium)
9. `#34` — Self-service onboarding (medium, depends on #30)
10. `#35` — Config promotion / release channels (medium)
11. `#36` — Client compatibility profiles (medium)
12. `#43` — PostgreSQL MCP custom server (low, depends on #39)
13. `#37` — Evaluation-driven routing (low)

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
Worktree: ../ai-gateway-$SHORT_NAME
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

```bash
cd /home/dev/repos/ai-gateway

# Check which dev slots are free
./dev-env.sh list

# Create a worktree branching off main
git checkout main
git worktree add ../ai-gateway-<short-name> -b feat/<short-name>
ln -s /home/dev/repos/ai-gateway/.env /home/dev/repos/ai-gateway-<short-name>/.env
cd /home/dev/repos/ai-gateway-<short-name>

# Start an isolated dev stack on a free slot (e.g. slot 1)
./dev-env.sh start <slot>
```

**Never edit files in `/home/dev/repos/ai-gateway` directly — that is the stable stack.**
**Never use slot 0 — that is the stable production stack on port 4000.**

---

## Step 4 — Implement the issue

Read the full issue body carefully. Follow the **Actions** and satisfy the **Acceptance criteria**.

During implementation:
- Make changes — the translator hot-reloads in ~1s, litellm-config.yaml hot-reloads in ~10s
- After each significant change, run unit tests:
  ```bash
  docker exec aidev<slot>-translator-1 pytest test_translator.py -v
  ```
- For gateway/wire-format changes, also run the fast mock integration tier:
  ```bash
  ./dev-env.sh start-mock 9
  ./dev-env.sh test-mock 9
  ./dev-env.sh stop-mock 9
  ```
  The mock tier runs translator + LiteLLM + a canned CLIProxy upstream, requires no OAuth, and must have **0 skips**.
- All translator unit tests must pass before continuing
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
# Fast mock integration tier (required for translator/wire-format/config routing changes)
./dev-env.sh start-mock 9
./dev-env.sh test-mock 9
./dev-env.sh stop-mock 9

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

## Step 6 — Open a PR to main

**Never push directly to main.** Open a PR so CI runs and leaves a review trail.

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
- [ ] Translator unit tests pass (41/41)
- [ ] Mock integration tier passes with 0 skips (`./dev-env.sh test-mock 9` or `make test-mock`)
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

**If CI fails:**
1. Read the failure output
2. Fix the issue in your worktree
3. Push the fix to your PR branch
4. CI will re-run automatically
5. The auto-merge will proceed once all required fast-tier checks are green

**Required fast-tier CI checks that must pass:**
- `lint-and-syntax` — ruff check + format, shell syntax, YAML syntax, no hardcoded keys
- `unit-tests` — translator unit tests
- `multi-repo-isolation` — environment isolation checks
- `mock-integration` — translator + LiteLLM + mock upstream integration tests (0 skips)

**Gated CI check:**
- `real-provider-e2e` — runs only on `workflow_dispatch` or PR label `run-e2e`; not required by default

---

## Step 8 — Gate D: post-merge verification on stable (main)

After the PR merges, from the **stable worktree** on `main`:

```bash
cd /home/dev/repos/ai-gateway
git pull origin main

# Gate D — production-like stack on port 4000
./cliproxy-setup.sh health
./cliproxy-setup.sh test claude-sonnet-4-6
./cliproxy-setup.sh test gemini-3-flash
./cliproxy-setup.sh test gpt-5-4
```

All three model tests must return a valid response. Record results in the closeout comment.

---

## Step 9 — Close the issue and clean up

```bash
# Post completion summary on the issue
gh issue comment $ISSUE --repo echoares-lab/ai-gateway --body "$(cat <<'EOF'
✅ DONE

- PR: #<pr-number>
- Merge commit: <sha>
- Gates run:
  - Gate A: lint-and-syntax, unit-tests (test_translator*.py)
  - Gate B: mock-integration (0 skips)
  - Gate C: real-provider-e2e (if high-risk / run-e2e label)
  - Gate D: cliproxy-setup health + 3 model smokes on stable (:4000)
- Verified on: main (production)
- Follow-up issues: none / #NNN
EOF
)"

# Close the issue
gh issue close $ISSUE --repo echoares-lab/ai-gateway

# Clean up dev stack and worktree
./dev-env.sh stop <slot>
cd /home/dev/repos/ai-gateway
git worktree remove ../ai-gateway-<short-name>
git branch -d feat/<short-name>
```

---

## Quick reference — test commands

| Command | When |
|---------|------|
| `docker exec aidev<slot>-translator-1 pytest test_translator*.py -v` | Gate A — after every significant change |
| `make test-fast` | Gate A + B — local equivalent of required CI fast tier |
| `make test-mock` | Gate B only — mock stack, 0 skips |
| `./dev-env.sh test <slot>` | Gate C — real-provider integration when broader coverage needed |
| `gh pr edit <pr> --add-label run-e2e` | Trigger Gate C in CI (`real-provider-e2e`) |
| `./cliproxy-setup.sh health` | Gate D — before and after merge on stable |
| `./cliproxy-setup.sh test <model>` | Gate D — post-merge model smoke on stable |

---

## What NOT to do

- ❌ Do NOT push directly to `main`
- ❌ Do NOT edit files in the main `/home/dev/repos/ai-gateway` worktree during development
- ❌ Do NOT claim an issue that already has an assignee
- ❌ Do NOT skip unit tests
- ❌ Do NOT hardcode API keys anywhere
- ❌ Do NOT close an issue before the PR is merged to main and E2E passes
- ❌ Do NOT work on a parent epic issue — only concrete sub-issues are claimable work units

---

## Conflict avoidance

If two agents are running simultaneously:
- Each agent works a **different issue** (enforced by the assignee check in Step 2)
- Each agent uses a **different dev slot** (check `./dev-env.sh list` before starting)
- Each agent uses a **different worktree** (different directory and branch name)
- Issues touching the same files are serialized by the dependency graph — check `Depends on:` in the issue body

The stable stack on port 4000 is never touched by any agent.
