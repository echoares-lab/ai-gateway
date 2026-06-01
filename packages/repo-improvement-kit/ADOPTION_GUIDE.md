# Adoption Guide

Use this checklist when copying the Repo Improvement Kit into another repository.

## 1. Copy files

Copy these files/folders into the target repo:
- `REPO_IMPROVEMENT_WORKFLOW.md`
- `REPO_IMPROVEMENT_APPENDIX.template.md` as `REPO_IMPROVEMENT_APPENDIX.md`
- `AGENT_DISPATCH.template.md` as `AGENT_DISPATCH.md`
- `.github/ISSUE_TEMPLATE/repo-improvement.yml`
- `.github/ISSUE_TEMPLATE/config.yml`
- `.github/pull_request_template.md`
- `.github/CODEOWNERS`
- `.github/BRANCH_PROTECTION_POLICY.md`

## 2. Customize the repo-specific appendix

In `REPO_IMPROVEMENT_APPENDIX.md`, update:
- branch strategy, defaulting to `main -> feature worktree/branch -> PR -> main`
- environment/staging flow
- CI-enforced checks
- manual verification commands
- useful local commands
- issue body conventions already in use

## 2a. Customize the agent dispatch prompt

In `AGENT_DISPATCH.md`, replace the placeholders from `AGENT_DISPATCH.template.md`:
- `<OWNER>/<REPO>` and `<LOCAL_REPO_PATH>`
- environment/slot commands (or remove if not applicable)
- unit, integration, smoke, and health-check commands
- post-merge verification commands
- priority order specific to the repo (epics vs sub-issues, etc.)

## 3. Update owners

Edit `.github/CODEOWNERS`:
- replace placeholder owner handles with the correct owner/team handles
- add any team-specific ownership rules

## 4. Update security reporting

Edit `.github/ISSUE_TEMPLATE/config.yml`:
- replace the placeholder security advisory URL with the target repo’s private reporting route
- remove the contact link if the repo has no private security disclosure process

## 5. Update issue template defaults

Edit `.github/ISSUE_TEMPLATE/repo-improvement.yml` if needed:
- default labels
- work types
- acceptance criteria phrasing
- required tests examples

## 6. Update PR checklist

Edit `.github/pull_request_template.md` to match the repo’s real test gates:
- unit test command
- integration command
- E2E/smoke checks
- rollout/rollback expectations

## 7. Configure branch protection manually in GitHub

GitHub branch protection is not stored in git. Use `.github/BRANCH_PROTECTION_POLICY.md` as the source of truth.

## 8. Create labels

Create these labels in the target repo:
- `status:*`
- `type:*`
- `area:*`
- `priority:*`

## 9. Optional enhancements

Also consider adding:
- issue forms for bugs/features/security reports
- PR automation / merge queue
- stale-claim automation
- CODEOWNERS team review rules
- branch naming checks
