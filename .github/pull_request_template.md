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

- [ ] `make lint` pass
- [ ] `make test-unit` pass (`pytest test_translator*.py`)
- [ ] YAML validation pass (if `litellm-config.yaml` changed)

### Gate B — mock integration (required for medium/high; optional for low)

- [ ] `make test-mock` pass (0 skips; `ALLOW_MODEL_SKIP=0`)

### Gate C — real providers (high-risk only)

- [ ] `make test-e2e` pass **or** PR label `run-e2e` (CI `real-provider-e2e`)

Required for changes touching: `translator.py`, `litellm-config.yaml`, compose files, cliproxy.

### Gate D — post-merge stable (record in closeout, not pre-merge)

- [ ] `./cliproxy-setup.sh health` on port 4000
- [ ] `./cliproxy-setup.sh test claude-sonnet-4-6`
- [ ] `./cliproxy-setup.sh test gemini-3-flash`
- [ ] `./cliproxy-setup.sh test gpt-5-4`

### CI

- [ ] `lint-and-syntax`, `unit-tests`, `multi-repo-isolation`, `mock-integration` passed

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
