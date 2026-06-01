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

## Required checks

- Unit tests: `<unit-test-command>`.
- Integration tests: `<integration-test-command>`.
- Config/schema validation: `<validation-command>`.
- Lint/format checks: `<lint-command>`.

## Manual E2E verification

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
