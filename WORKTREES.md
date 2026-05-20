# Git Worktrees — AI Gateway

This project uses git worktrees to manage multiple features and environments simultaneously without switching branches in the same directory.

## Active Worktrees

| Directory | Branch | Commit | Purpose |
|-----------|--------|--------|---------|
| `/home/dev/repos/ai-gateway` | `main` | `06a4e39` | Primary production-ready gateway config. |
| `/home/dev/repos/ai-gateway-model-provider` | `feat/model-provider` | `06a4e39` | Experimental work on model provider expansion. |
| `/home/dev/repos/ai-gateway-antigravity` | `feat/antigravity-integration` | `06a4e39` | Integration testing for Antigravity CLI. |

## Management

To list all worktrees:
```bash
git worktree list
```

To add a new worktree:
```bash
git worktree add ../new-feature-dir branch-name
```

To remove a worktree:
```bash
git worktree remove <directory>
```
