# Recommended Branch Protection Policy

This file documents the GitHub branch protection settings that should be applied manually.

## `main`

Recommended:
- Require a pull request before merging
- Require at least 1 approval
- Dismiss stale pull request approvals when new commits are pushed
- Require status checks to pass before merging
- Require branches to be up to date before merging
- Required checks:
  - `lint`
  - `yaml-validate`
  - `test`
- Require conversation resolution before merging
- Restrict direct pushes
- Allow auto-merge only when all checks pass
- Do not allow force pushes
- Do not allow deletions

## Optional integration branch

Recommended:
- Require status checks to pass before merging
- Required checks:
  - `lint`
  - `yaml-validate`
  - `test`
- Do not allow force pushes
- Optionally allow direct pushes by maintainers if your team prefers a faster integration branch
- Prefer PRs for risky changes

## Notes

These settings are not stored in git; they must be configured in GitHub repo settings.
Use this file as the source of truth when re-creating repo settings in another repository.
If the repo does not use a separate integration branch, create feature worktrees or branches from
`main`, test there, and merge back to `main` through protected PRs.
