## Summary

- What changed and why?

## Linked issues

- Fixes #
- Depends on #
- Bundle #

## Scope / non-goals

- In scope:
- Out of scope:

## Dependency notes

- Hard dependencies merged? Yes / No
- Any bundled issues included? List them

## Test plan (gates)

Risk level: **low / medium / high** (see `TESTING_AND_PROMOTION_POLICY.md`)

### Gate A — lint, schema, unit (required for all PRs)

- [ ] Lint / format pass (`<gate-a-lint-command>`)
- [ ] Unit tests pass (`<unit-test-command>`)
- [ ] Config/schema validation passes (`<validation-command>`)

### Gate B — mock integration (required for medium/high; optional for low)

- [ ] Mock integration pass (`<gate-b-command>`)

### Gate C — real providers (high-risk only; label or maintainer trigger)

- [ ] Real-provider smoke pass (`<gate-c-command>` or PR label `<run-e2e-label>`)

### Gate D — post-merge stable (after merge to trunk; not pre-merge)

- [ ] Stable health + smoke recorded in closeout (`<gate-d-command>`)

### CI

- [ ] Required CI checks passed (see appendix for job names)

## Risk / rollback

- Risk level: low / medium / high
- Rollback plan:

## Operational notes

- Any config, auth, provider, or infra changes?
- Any manual post-merge verification needed?

## Workflow checklist

- [ ] Issue was approved before implementation
- [ ] Issue was claimed with a start-work comment (Claim-ID, branch, worktree, slot)
- [ ] Dependencies were handled explicitly
- [ ] Required manual verification is recorded here
- [ ] This PR is ready to merge to the target branch
