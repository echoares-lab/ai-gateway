# Git Worktrees — AI Gateway

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
# Always branch off dev (not main)
cd /home/dev/repos/ai-gateway
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
| `/home/dev/repos/ai-gateway` | `dev` | Primary repo — stable stack reads from here |

---

## Branch strategy

```
feat/<name>  →  dev  →  (PR)  →  main
```

- All feature work branches off `dev`
- Features merge back to `dev` after testing
- `dev` → `main` via PR (CI must pass; never direct push)
- `main` is the production branch — only tested, reviewed code lands here

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
