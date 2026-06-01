# Repo Improvement Kit

Portable governance/docs package for multi-agent repository improvement workflows.

The default workflow assumes feature branches or worktrees are created from
`main`, tested in isolation, and merged back to `main` through pull requests.
Repos that use a separate integration branch can document that in the
repo-specific appendix.

## What this kit contains

- `REPO_IMPROVEMENT_WORKFLOW.md` — reusable process for discovery, approval, issue creation, claiming, execution, merge, and promotion
- `REPO_IMPROVEMENT_APPENDIX.template.md` — repo-specific appendix template for branch, environment, and verification details
- `.github/ISSUE_TEMPLATE/repo-improvement.yml` — standardized improvement issue template
- `.github/ISSUE_TEMPLATE/config.yml` — issue-template config and security reporting link placeholder
- `.github/pull_request_template.md` — PR checklist with tests, dependencies, and rollout notes
- `.github/CODEOWNERS` — sample CODEOWNERS file
- `.github/BRANCH_PROTECTION_POLICY.md` — branch protection settings to apply in GitHub UI
- `ADOPTION_GUIDE.md` — how to customize this kit for another repo

## How to use in another repo

1. Copy the entire `packages/repo-improvement-kit/` folder into the target repo.
2. Move the `.github/*` contents into that repo’s `.github/` directory.
3. Keep `REPO_IMPROVEMENT_WORKFLOW.md` at repo root (or docs/process/).
4. Copy `REPO_IMPROVEMENT_APPENDIX.template.md` to `REPO_IMPROVEMENT_APPENDIX.md` and fill it in for the target repo.
5. Replace placeholder owners in `CODEOWNERS`.
6. Replace the placeholder security disclosure URL in `.github/ISSUE_TEMPLATE/config.yml`.
7. Configure GitHub branch protection manually using `BRANCH_PROTECTION_POLICY.md`.
8. Add labels described in the workflow doc (`status:*`, `type:*`, `area:*`, `priority:*`).

## Suggested repo-specific edits

- branch strategy (`main -> feature worktree/branch -> PR -> main` by default)
- environment / staging model
- test commands
- owner handles
- CI check names
- security disclosure URL

See `ADOPTION_GUIDE.md` for a checklist.
