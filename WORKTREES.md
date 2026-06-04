# Git Worktrees — AI Gateway

See also: `TESTING_AND_PROMOTION_POLICY.md`, `REPO_IMPROVEMENT_APPENDIX.md`.

## Why worktrees?

The stable gateway stack runs on **port 4000** and serves live traffic. If you
switch branches in the main repo directory while the stack is running, Docker's
volume mounts pick up the new files immediately and can silently break the live
gateway. Worktrees solve this:

- Each worktree is an independent checkout of the repo in a separate directory
- The stable stack always reads from `/home/dev/repos/ai-gateway` (never changes)
- Feature work happens in `/home/dev/repos/ai-gateway-<feature>` (isolated)
- Dev stacks started with `./dev-env.sh start <slot>` use different ports, so
  the stable stack is never touched

---

## Creating a feature worktree

```bash
# Always branch off main
cd /home/dev/repos/ai-gateway
git checkout main
git worktree add ../ai-gateway-<feature> -b feat/<feature>

# Symlink .env so secrets are available without duplicating the file
ln -s /home/dev/repos/ai-gateway/.env /home/dev/repos/ai-gateway-<feature>/.env

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

- All feature work branches off `main` (no long-lived `dev` branch)
- `feat/<name>` → `main` via PR (Gate A + B CI must pass; never direct push)
- `main` is the production branch — only tested, reviewed code lands here

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

```bash
# Stop the dev stack
./dev-env.sh stop 1

# Remove the worktree
cd /home/dev/repos/ai-gateway
git worktree remove ../ai-gateway-<feature>
git branch -d feat/<feature>
```

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
