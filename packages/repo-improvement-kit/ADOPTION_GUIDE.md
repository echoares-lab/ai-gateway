# Adoption Guide

Use this checklist when copying the Repo Improvement Kit into another repository.

## 1. Copy files

Copy these files/folders into the target repo:
- `REPO_IMPROVEMENT_WORKFLOW.md`
- `.github/ISSUE_TEMPLATE/repo-improvement.yml`
- `.github/ISSUE_TEMPLATE/config.yml`
- `.github/pull_request_template.md`
- `.github/CODEOWNERS`
- `.github/BRANCH_PROTECTION_POLICY.md`

## 2. Customize the repo-specific appendix

In `REPO_IMPROVEMENT_WORKFLOW.md`, update:
- branch strategy
- environment/staging flow
- CI-enforced checks
- manual verification commands
- useful local commands
- issue body conventions already in use

## 3. Update owners

Edit `.github/CODEOWNERS`:
- replace `@TheNorthWestPassage` with the correct owner/team handles
- add any team-specific ownership rules

## 4. Update issue template defaults

Edit `.github/ISSUE_TEMPLATE/repo-improvement.yml` if needed:
- default labels
- work types
- acceptance criteria phrasing
- required tests examples

## 5. Update PR checklist

Edit `.github/pull_request_template.md` to match the repo’s real test gates:
- unit test command
- integration command
- E2E/smoke checks
- rollout/rollback expectations

## 6. Configure branch protection manually in GitHub

GitHub branch protection is not stored in git. Use `.github/BRANCH_PROTECTION_POLICY.md` as the source of truth.

## 7. Create labels

Create these labels in the target repo:
- `status:*`
- `type:*`
- `area:*`
- `priority:*`

## 8. Optional enhancements

Also consider adding:
- issue forms for bugs/features/security reports
- PR automation / merge queue
- stale-claim automation
- CODEOWNERS team review rules
- branch naming checks
