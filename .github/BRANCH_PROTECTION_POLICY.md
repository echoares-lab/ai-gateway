# Recommended Branch Protection Policy

This file documents the GitHub branch protection settings that should be applied manually.

## `main`

Recommended:
- Require a pull request before merging
- Require at least 1 approval
- Dismiss stale pull request approvals when new commits are pushed
- Require status checks to pass before merging
- Require branches to be up to date before merging
- Required checks (must match [`.github/workflows/ci.yml`](workflows/ci.yml) job names exactly):
  - `lint-and-syntax`
  - `unit-tests`
  - `multi-repo-isolation`
  - `mock-integration`
- Require conversation resolution before merging
- Restrict direct pushes
- Allow auto-merge only when all checks pass
- Do not allow force pushes
- Do not allow deletions

**Not required (Gate C — hybrid):**
- `real-provider-e2e` — runs on `workflow_dispatch`, PR label `run-e2e`, or [nightly schedule](workflows/nightly-integration.yml)

## Notes

These settings are not stored in git; they must be configured in GitHub repo settings.
Use this file as the source of truth when re-creating repo settings.

This repo uses **`main` only** (no long-lived integration branch). Feature worktrees branch from `main` and merge back via PR.

See [`TESTING_AND_PROMOTION_POLICY.md`](../TESTING_AND_PROMOTION_POLICY.md) and [`REPO_IMPROVEMENT_APPENDIX.md`](../REPO_IMPROVEMENT_APPENDIX.md) for gate commands.
