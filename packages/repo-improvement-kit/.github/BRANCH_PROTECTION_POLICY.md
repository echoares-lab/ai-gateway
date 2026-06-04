# Recommended Branch Protection Policy

This file documents the GitHub branch protection settings that should be applied manually.

## `main`

Recommended:
- Require a pull request before merging
- Require at least 1 approval
- Dismiss stale pull request approvals when new commits are pushed
- Require status checks to pass before merging
- Require branches to be up to date before merging
- Required checks (must match CI job names exactly — see repo appendix):
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
- `real-provider-e2e` — runs on `workflow_dispatch`, PR label `run-e2e`, or nightly schedule

## Optional integration branch

If the repo uses a separate integration branch, document it in `REPO_IMPROVEMENT_APPENDIX.md`.

Recommended:
- Require status checks to pass before merging
- Required checks: same Gate A + B jobs as `main` (use appendix for exact names)
- Do not allow force pushes
- Prefer PRs for risky changes

## Notes

These settings are not stored in git; they must be configured in GitHub repo settings.
Use this file as the source of truth when re-creating repo settings in another repository.
If the repo does not use a separate integration branch, create feature worktrees or branches from
`main`, test there, and merge back to `main` through protected PRs.

See `TESTING_AND_PROMOTION_POLICY.md` for gate definitions (A/B/C/D).
