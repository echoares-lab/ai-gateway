# Recommended Branch Protection Policy

This file documents the GitHub branch protection settings that should be applied manually.

## `main`

Recommended:
- Require a pull request before merging
- **No approving review required** (solo-dev / self-merge workflow — GitHub does not allow authors to approve their own PRs; use PR + CI instead of external review)
- Dismiss stale pull request approvals when new commits are pushed (applies if reviews are added voluntarily)
- Require status checks to pass before merging
- Require branches to be up to date before merging
- Required checks (must match [`.github/workflows/ci.yml`](workflows/ci.yml) job names exactly):
  - `lint-and-syntax` — **Required — Fast (Gate A)**
  - `unit-tests` — **Required — Fast (Gate A)**
  - `build-translator` — builds shared translator image (required dependency)
  - `multi-repo-isolation` — **Required — Conditional** (isolation script paths)
  - `mock-integration` — **Required — Conditional (Gate B)** (runtime paths)
- Require conversation resolution before merging
- Restrict direct pushes
- Allow auto-merge only when all checks pass
- Do not allow force pushes
- Do not allow deletions

### Conditionally required (path-filtered; skipped counts as pass)

| Job | Gate | Triggers when |
|-----|------|---------------|
| `credential-prober` | A | `services/credential-prober/**` changes |
| `policy-engine-tests` | A | `services/policy-engine/**` changes |
| `litellm-reloader-tests` | A | `services/litellm-reloader/**` changes |
| `multi-repo-isolation` | A | isolation script paths change |
| `mock-integration` | B | runtime paths change |

### Gate C opt-in (not required for merge)

Gate C (`real-provider-e2e`) is **paused as a required check** pending an e2e refactor. It runs only when opted in:

- PR label `run-e2e`
- Manual `workflow_dispatch` on the CI workflow

Hotspot paths no longer auto-trigger Gate C in CI. Use the label or dispatch when real-provider smoke is needed.

### Docs-only PRs

When a PR touches only documentation and non-runtime paths, `mock-integration` and other conditional jobs may **skip**. GitHub treats skipped required checks as passing. Maintainers may use a `docs-only` label for audit visibility (optional ruleset bypass).

### Advisory (not required for merge)

- `real-provider-e2e` — Gate C real-provider smoke (opt-in via `run-e2e` label or `workflow_dispatch`)
- `nightly-integration` — scheduled Gate C matrix (report-only)
- `hotspot-e2e-reminder` — PR comment bot (suggests opt-in Gate C on hotspot paths)
- `post-merge-gate-d` — post-merge stable smoke on `main` (advisory)

## GitHub rulesets (optional)

For orgs using rulesets instead of classic branch protection:

- Create a **required** ruleset on `main` listing the checks above.
- Consider a separate ruleset or bypass for trusted `docs-only` automation.

## Notes

These settings are not stored in git; they must be configured in GitHub repo settings.
Use this file as the source of truth when re-creating repo settings.

This repo uses **`main` only** (no long-lived integration branch). Feature worktrees branch from `main` and merge back via PR.

See [`TESTING_AND_PROMOTION_POLICY.md`](../TESTING_AND_PROMOTION_POLICY.md), [`docs/TESTING.md`](../docs/TESTING.md), and [`REPO_IMPROVEMENT_APPENDIX.md`](../REPO_IMPROVEMENT_APPENDIX.md) for gate commands.
