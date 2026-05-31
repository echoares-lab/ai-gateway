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

## Test plan

- [ ] Translator unit tests pass (`docker compose exec translator pytest test_translator.py -v`)
- [ ] Integration tests pass on dev slot (`./dev-env.sh test <slot>`)
- [ ] Health check passes (`./cliproxy-setup.sh health`)
- [ ] Claude E2E passes (`./cliproxy-setup.sh test claude-sonnet-4-6`)
- [ ] Gemini E2E passes (`./cliproxy-setup.sh test gemini-3-flash`)
- [ ] GPT E2E passes (`./cliproxy-setup.sh test gpt-5-4`)
- [ ] CI checks passed

## Risk / rollback

- Risk level: low / medium / high
- Rollback plan:

## Operational notes

- Any config, auth, provider, or infra changes?
- Any manual post-merge verification needed?

## Workflow checklist

- [ ] Issue was approved before implementation
- [ ] Issue was claimed with a start-work comment
- [ ] Dependencies were handled explicitly
- [ ] Required manual verification is recorded here
- [ ] This PR is ready to merge to the target branch
