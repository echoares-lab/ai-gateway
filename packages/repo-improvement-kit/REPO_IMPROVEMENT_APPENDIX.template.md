# Repo Improvement Appendix: <Repo Name>

Repo-specific operating details for `REPO_IMPROVEMENT_WORKFLOW.md`.

## Branch and worktree policy

```text
main -> feat/* worktree/branch -> PR -> main
```

- Create feature worktrees or branches from `main`.
- Do not edit live or stable worktrees for feature work.
- Document any optional integration or staging branch here.

## Environment strategy

- Stable environment: `<stable-environment>`.
- Isolated test environment: `<test-environment-command>`.
- Local service ports: `<ports-or-not-applicable>`.

## Test gates

See `TESTING_AND_PROMOTION_POLICY.md` for portable gate definitions and risk tiers.

| Gate | Purpose | Local command | CI job name(s) |
|------|---------|---------------|----------------|
| **A** | Lint, schema, unit tests | `<gate-a-local>` | `<gate-a-ci-jobs>` |
| **B** | Mock/deterministic integration | `<gate-b-local>` | `<gate-b-ci-jobs>` |
| **C** | Real providers / staging smoke | `<gate-c-local>` | `<gate-c-ci-jobs>` |
| **D** | Post-merge stable verification | `<gate-d-local>` | n/a (manual) |

### Risk tiers (PR checklist)

| Risk | Gate A | Gate B | Gate C | Gate D |
|------|--------|--------|--------|--------|
| Low (docs, templates) | yes | optional | no | no |
| Medium (logic, tests) | yes | yes | no | no |
| High (auth, config, infra) | yes | yes | smoke | post-merge on stable |

### Parallel agent isolation

- One feature worktree + branch + runtime slot per active claim.
- Stable slot reserved; declare slot and mock vs real in claim comment.
- See `TESTING_AND_PROMOTION_POLICY.md` section 3.

## Required checks (Gate A + B)

- Unit tests: `<unit-test-command>`.
- Integration tests: `<integration-test-command>`.
- Config/schema validation: `<validation-command>`.
- Lint/format checks: `<lint-command>`.

## Manual E2E verification (Gate C + D)

- Smoke test: `<smoke-test-command>`.
- Health check: `<health-check-command>`.
- Rollback verification: `<rollback-check-command>`.

## Hotspot files and areas

- `<critical-runtime-path>`.
- `<critical-config-path>`.
- `<deployment-or-infra-path>`.

## Useful commands

- `<start-test-environment-command>`.
- `<stop-test-environment-command>`.
- `<run-local-checks-command>`.
