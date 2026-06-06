# Git Worktrees — AI Gateway

See also: `TESTING_AND_PROMOTION_POLICY.md`, `REPO_IMPROVEMENT_APPENDIX.md`.

## Why worktrees?

The stable gateway stack runs on **port 4000** and serves live traffic. If you
switch branches in the main repo directory while the stack is running, Docker's
volume mounts pick up the new files immediately and can silently break the live
gateway. Worktrees solve this:

- Each worktree is an independent checkout of the repo in a separate directory
- The stable stack always reads from `/home/dev/repos/ai-gateway` (never changes)
- Feature work happens under `/home/dev/worktrees/ai-gateway-<feature>` (isolated)
- Dev stacks started with `./dev-env.sh start <slot>` use different ports, so
  the stable stack is never touched

---

## Worktree location (required)

| Path | Purpose |
|------|---------|
| `/home/dev/repos/ai-gateway` | **Stable checkout only** — `main`, serves port 4000 |
| `/home/dev/worktrees/ai-gateway-<feature>` | **Feature worktrees** — all agent development |

**Do not** create feature worktrees:

- As siblings of the stable repo (`/home/dev/repos/ai-gateway-*`) — clutters the repos folder and confuses tooling
- Inside the repo tree — including `.claude/worktrees/`, `.cursor/`, or any hidden subdirectory
- In IDE-managed paths unless the appendix explicitly says otherwise

Create the worktrees root once per machine:

```bash
mkdir -p /home/dev/worktrees
```

Claim comments must record the **full absolute path** (e.g. `/home/dev/worktrees/ai-gateway-issue-89`).

---

## Creating a feature worktree

```bash
# Always branch off main; worktrees live outside the repos/ folder
mkdir -p /home/dev/worktrees
cd /home/dev/repos/ai-gateway
git checkout main
git worktree add /home/dev/worktrees/ai-gateway-<feature> -b feat/<feature>

# Symlink .env so secrets are available without duplicating the file
ln -s /home/dev/repos/ai-gateway/.env /home/dev/worktrees/ai-gateway-<feature>/.env
cd /home/dev/worktrees/ai-gateway-<feature>

# Start an isolated dev stack (see dev-env.sh list for free slots)
./dev-env.sh start 1
```

---

## Current worktrees

Run `git worktree list` for the live state.

| Directory | Branch | Purpose |
|-----------|--------|---------|
| `/home/dev/repos/ai-gateway` | `main` | Primary repo — stable stack reads from here |

---

## Branch strategy

```
feat/<name>  →  (PR)  →  main
```

- All feature work branches off `main` when there is no open dependency (no long-lived `dev` branch)
- `feat/<name>` → `main` via PR (Gate A + B CI must pass; never direct push)
- `main` is the production branch — only tested, reviewed code lands here

### Stacked branches (parallel agents)

When issue B depends on issue A and A's PR is still open:

```bash
# Branch B from A's feature branch (only while A's PR is open and CI-green)
git worktree add /home/dev/worktrees/ai-gateway-<b> -b feat/<b> feat/<a>
# Open PR with base feat/<a>
```

After A merges to `main`, rebase B:

```bash
cd /home/dev/worktrees/ai-gateway-<b>
git fetch origin && git rebase origin/main
make test-fast
git push --force-with-lease origin feat/<b>
# PR base should be main
```

Poll before claiming: `gh issue view <dep> --json state,closed` and `gh pr view <pr> --json state,mergedAt`.

Issues touching the same hotspot (e.g. `translator.py`) must serialize via `Depends on:` or this stack-then-rebase pattern.

---

## Slot registry

One active claim = one worktree + one branch + one slot.

| Slot | Purpose |
|------|---------|
| 0 | Stable stack (:4000) — **never use for feature work** |
| 1–8 | Real OAuth dev stacks (Gate C) |
| 9 | Mock stack (Gate B) — `make test-mock` default |

Before starting a stack: `./dev-env.sh list`. Declare your slot in the issue claim comment.
Do not share slots between concurrent claims without an explicit handoff.

---

## Testing quick reference

| When | Command |
|------|---------|
| During development (Gate A) | `make test-unit` |
| Before PR (Gate A + B) | `make test-fast` |
| High-risk pre-merge (Gate C) | `make test-e2e` or PR label `run-e2e` |
| After merge (Gate D) | `./cliproxy-setup.sh health` + 3 model smokes on :4000 |

---

## Cleanup

**When:** After the PR merges to `main` and Gate D passes — not while the PR is open.

```bash
# Stop the dev stack (use your claimed slot)
./dev-env.sh stop <slot>

# Remove the worktree and local branch
cd /home/dev/repos/ai-gateway
git worktree remove /home/dev/worktrees/ai-gateway-<feature>
git branch -d feat/<feature>

# Verify
git worktree list
./dev-env.sh list
```

**If removal fails** (uncommitted changes or running containers):

```bash
cd /home/dev/worktrees/ai-gateway-<feature>
git stash push -m "pre-cleanup"   # or commit if still needed
./dev-env.sh stop <slot>
cd /home/dev/repos/ai-gateway
git worktree remove /home/dev/worktrees/ai-gateway-<feature>
git worktree prune
```

Parent/coordinator agents should confirm no orphaned worktrees or occupied slots before
closing epics. Keep the stable checkout at `/home/dev/repos/ai-gateway` clean — do not
use it for feature edits; a dirty stable tree blocks `git pull` for Gate D.

---

## Reference commands

| Command | Effect |
|---------|--------|
| `git worktree list` | Show all active worktrees and their branches |
| `git worktree add <path> -b <branch>` | Create new worktree on new branch |
| `git worktree add <path> <existing-branch>` | Check out existing branch in new worktree |
| `git worktree remove <path>` | Remove a worktree (branch is preserved) |
| `git worktree prune` | Clean up stale worktree metadata |
| `./dev-env.sh list` | Show all running dev stack containers |
