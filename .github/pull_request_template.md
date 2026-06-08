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

## Test plan (tiered gates)

Risk level: **low / medium / high** (see `TESTING_AND_PROMOTION_POLICY.md` and `docs/TESTING.md`)

### Required — Fast (Gate A) — every PR

- [ ] `make lint` pass
- [ ] `make test-unit` pass (gateway-engine + policy-engine; `-n auto`)
- [ ] YAML validation pass (if `litellm-config.yaml` changed)

### Required — Conditional (Gate A/B) — when matching paths change

- [ ] `make test-mock` pass (0 skips; runtime paths)
- [ ] `bash tests/test-multi-repo-isolation.sh` (isolation script paths)
- [ ] Policy-engine / credential-prober tests (service paths)

### Gate C — real providers (opt-in; high-risk only)

- [ ] `make test-e2e` pass **or** PR label `run-e2e` (CI `real-provider-e2e`)

Not required to merge (Gate C paused pending e2e refactor). Opt in via label or CI `workflow_dispatch` when real-provider smoke is needed.

### Advisory — not merge-blocking

- [ ] `real-provider-e2e` (only when `run-e2e` label or manual dispatch)
- [ ] `nightly-integration` (scheduled)
- [ ] `post-merge-gate-d` (after merge to `main`)

### Gate D — post-merge stable (record in closeout)

- [ ] `./cliproxy-setup.sh health` on port 4000
- [ ] `./cliproxy-setup.sh test claude-sonnet-4-6`
- [ ] `./cliproxy-setup.sh test gemini-3-flash`
- [ ] `./cliproxy-setup.sh test gpt-5-4`

### CI required checks

- [ ] `lint-and-syntax`, `unit-tests`, `build-gateway-engine`
- [ ] `mock-integration` (runtime paths; skipped OK on docs-only)

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
