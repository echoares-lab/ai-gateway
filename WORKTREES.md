# Git Worktrees — AI Gateway

This project uses git worktrees to manage multiple features and environments simultaneously without switching branches in the same directory.

## Active Worktrees

As of last update — run `git worktree list` for the live state.

| Directory | Branch | Purpose |
|-----------|--------|---------|
| `/home/dev/repos/ai-gateway` | `dev` | Primary development branch |

## Notable Remote Branches

Feature branches available for checkout / new worktrees:

| Branch | Purpose |
|--------|---------|
| `origin/dev` | Active development (ahead of main) |
| `origin/main` | Stable production config |
| `origin/feat/credential-observability` | Per-credential metrics |
| `origin/feat/streaming-cache` | SSE streaming cache improvements |
| `origin/feat/translator-connection-pool` | httpx pool tuning |
| `origin/feat/translator-multi-worker` | Multi-worker uvicorn support |
| `origin/fix/gemini-claude-model-parsing` | Model name parsing fix |

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
