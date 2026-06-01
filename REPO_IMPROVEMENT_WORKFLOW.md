# Multi-Agent Repository Improvement Workflow

This document defines a reusable process for continuously improving a repository with many human and AI agents working in parallel.

It is designed to support recurring review and execution of:

- security issues
- performance issues
- reliability issues
- code health / maintainability issues
- test / observability gaps
- optional feature ideas

It separates **discovery**, **approval**, **execution**, and **promotion** so production branches remain stable while many agents work in parallel.

---

## 1. Core principles

1. **No implementation without an approved issue.**
   Discovery and execution are separate phases.

2. **One claimable issue = one mergeable unit.**
   If an issue is too large to merge safely, split it before work starts.

3. **Parallelism requires explicit ownership.**
   A branch name alone is not a claim. Claiming requires a visible GitHub state change.

4. **Machine checks and human checks are different.**
   CI can prove some things; end-to-end and operational verification still need explicit signoff.

5. **Promotion must be staged.**
   Changes should move through feature → integration → production, not jump straight to stable.

6. **Evidence must live in repo artifacts.**
   Test results, claim status, risk notes, and closeout notes belong in issues and PRs, not only in chat.

---

## 2. Work types

Every candidate item should be classified as one primary type:

- `type:security`
- `type:performance`
- `type:reliability`
- `type:code-health`
- `type:test`
- `type:observability`
- `type:docs`
- `type:dx`
- `type:feature`

This classification drives labels, expected tests, and promotion strictness.

---

## 3. Recurring improvement review

Improvement work begins with a recurring repo review, not immediate coding.

### Review modes

**A. Maintenance review**
Focus on:
- security problems
- reliability regressions
- flaky tests
- dependency drift
- performance bottlenecks
- observability gaps
- docs drift
- operational pain

**B. Opportunity review**
Optional mode that also proposes:
- feature ideas
- developer tooling improvements
- UX/API enhancements
- automation opportunities

### Suggested cadence

- weekly: maintenance review
- biweekly or monthly: architecture / feature opportunity review

### Review inputs

Use any or all of:
- recent PRs and commits
- CI failures and flaky tests
- incident notes / outages
- dependency advisories
- high-churn files
- TODO/FIXME hotspots
- known manual toil
- slow or error-prone code paths
- stale docs vs actual process

### Review output format

Each candidate should be proposed in a standard structure:

- **Summary**
- **Problem**
- **Why it matters**
- **Proposed action**
- **Expected risk**
- **Affected files / systems**
- **Dependencies**
- **Suggested labels**
- **Suggested tests**

Candidates are not active work yet. They must pass through approval.

---

## 4. Approval gate

Every candidate must be explicitly triaged before becoming active work.

### Approval states

- `proposed`
- `approved`
- `deferred`
- `rejected`

### Approval criteria

Evaluate each candidate on:
- impact
- urgency
- confidence
- blast radius
- testability
- dependency shape
- fit with current roadmap / stabilization priorities

### Rule

Only `approved` items become GitHub issues.

No agent may claim or implement:
- `proposed`
- `deferred`
- `rejected`

---

## 5. Issue creation standard

Every approved item becomes a GitHub issue with a strict template.

### Required issue sections

- **Summary**
- **Problem**
- **Why now**
- **Scope**
- **Non-goals**
- **Acceptance criteria**
- **Required tests**
- **Risks / rollback notes**
- **Dependencies**
- **Affected files / areas**
- **Suggested labels**
- **Execution notes**

### Suggested labels

At minimum:
- one `type:*` label
- one priority label (`priority:high`, `priority:medium`, `priority:low`)
- one area label (`area:translator`, `area:tests`, etc.)
- one status label (`status:ready`, `status:claimed`, etc.)

### Rule

Do not create vague “cleanup” issues. If the work is not small enough to merge safely, split it first.

---

## 6. Dependency model

Use two issue levels only:

### A. Atomic issue
A single mergeable unit of work.

### B. Bundle / epic
A parent coordination issue grouping related atomic issues.

### Dependency rules

- Parent bundle issues are **not claimable** unless they also contain concrete work.
- Child issues carry implementation.
- Prefer shallow dependency graphs.
- If two issues modify the same hotspot file or public interface, either:
  - serialize them with a dependency, or
  - combine them into one bundle

### Recommended issue fields

- `Depends on: #123, #124`
- `Blocks: #130`
- `Bundle: #120`

### Rule for dependency claiming

If an issue cannot safely be merged without another issue, the agent may claim the dependency bundle **only if**:
- the issues are tightly related
- the combined scope remains reviewable
- they touch the same subsystem / test surface

Otherwise, split or serialize.

---

## 7. Status model for parallel agents

GitHub open/closed is not enough. Use lifecycle states explicitly.

### Canonical statuses

- `proposed`
- `approved`
- `ready`
- `claimed`
- `in-progress`
- `blocked`
- `in-review`
- `changes-requested`
- `ci-failed`
- `ready-to-merge`
- `merged-to-integration`
- `verified-on-integration`
- `merged-to-production`
- `verified-on-production`
- `done`
- `deferred`
- `wontfix`

### Rule

Use statuses for lifecycle. Use labels for type, priority, area, and risk.

---

## 8. Claiming convention

This is the key to safe parallel work.

### A claim is valid only if all 3 happen

1. The issue is assigned.
2. A “start work” comment is posted.
3. The status changes to `claimed` or `in-progress`.

### Required start-work comment format

Every claim comment must include:
- agent name / owner
- branch name
- worktree name/path (if applicable)
- environment slot (if applicable)
- dependency issues included in the claim
- expected scope

### Example

```text
Starting work on #123.
Claiming: #123, #124
Branch: feat/cache-auth-key
Worktree: ../repo-cache-auth-key
Slot: 2
Scope: translator cache key + tests
```

### Stale claim policy

Recommended:
- soft stale after 24h without update
- reclaimable after 72h unless maintainer extends it

A reclaim should be visible in the issue thread.

---

## 9. Parallel-agent conflict avoidance

### Avoiding duplication

Use area labels to make ownership visible:
- `area:translator`
- `area:config`
- `area:tests`
- `area:docs`
- `area:infra`
- `area:scripts`

### Hotspot rule

If two issues both touch:
- the same critical file
- the same public interface
- the same deployment path

then they must be:
- serialized via dependency, or
- explicitly bundled

### Rule

Do not let two agents work the same hotspot without declaring it.

---

## 10. Branch, worktree, and environment workflow

General pattern:

```text
feature branch/worktree
  → integration branch/environment
  → production branch/environment
```

### Recommended execution flow

1. Create feature branch from integration branch
2. Create isolated worktree if supported
3. Start isolated dev/test environment if needed
4. Implement in small increments
5. Run fast tests continuously
6. Open PR to integration branch (or directly to production if repo policy allows)
7. Run CI + required manual checks
8. Promote to production only after integration verification

### Rule

Never develop directly on the stable/production worktree if the repo has a live local stack.

---

## 11. Validation gates

Separate machine-enforced gates from manual gates.

### A. Machine-enforced gates

These should block merges automatically.

Examples:
- linting
- unit tests
- YAML / JSON schema validation
- secret scanning
- dependency vulnerability scanning
- shell linting
- format checks

### B. Manual gates

These must be documented and recorded.

Examples:
- integration tests against a live stack
- health checks
- representative end-to-end tests
- smoke tests on production-like environment
- rollback rehearsal for risky changes

### Rule

Manual verification must be recorded in:
- the PR checklist, or
- the issue closeout comment

Never assume “tested in chat” is sufficient evidence.

---

## 12. PR standard

Every mergeable change should flow through a PR template.

### Required PR sections

- **Summary**
- **Linked issues**
- **Scope / non-goals**
- **Dependency notes**
- **Test plan**
- **Risk / rollback**
- **Operational notes** (if config / infra / auth touched)

### Required checkboxes

- [ ] issue approved and linked
- [ ] claim posted
- [ ] dependencies merged or accounted for
- [ ] required CI checks passed
- [ ] required manual checks completed
- [ ] rollback considered

### PR states

- draft
- ready for review
- blocked
- ready to merge
- auto-merge enabled

---

## 13. Merge and auto-merge policy

### Auto-merge is allowed only when

- required CI checks pass
- required reviews are complete
- no unresolved blocking comments exist
- dependency issues are merged
- PR checklist is complete
- branch protection allows it

### Recommended risk tiers

**Low risk**
- docs-only
- non-runtime tooling
- label/template updates

**Medium risk**
- internal logic changes
- test refactors
- non-critical scripts

**High risk**
- auth
- routing
- model/provider config
- deployment/infrastructure
- caching

### Rule

Healthy CI is necessary but not sufficient for high-risk production promotion.

---

## 14. Closure semantics

An issue should close only when the target outcome is actually achieved.

### Close only when

- implementation PR is merged
- required validation is complete for the intended branch/environment
- a closeout comment is posted

### Required closeout comment contents

- PR link
- merge commit hash
- summary of shipped change
- tests run
- any follow-up issues created
- whether the change is verified on integration only or on production too

### Rule

`merged-to-integration` is not the same as `done`.
If the issue target is production behavior, close after production verification.

---

## 15. Release channels, versioning, and staging

Versioning and staged promotion are key to avoiding regressions.

### Recommended release channels

- feature / worktree
- integration branch/environment
- staging / pre-prod (if available)
- production

### Versioning recommendations

- pin critical external images and runtime dependencies where possible
- upgrade via PR, not by silent mutable tags
- group risky provider/auth changes into explicit promotion windows
- use tags or releases for meaningful production milestones

### Suggested labels

- `release:patch`
- `release:minor`
- `release:risky`
- `channel:integration`
- `channel:production`

### Rule

Configuration that affects runtime behavior should be treated like code.

---

## 16. What should be automated vs manual

### Automate

High-value, low-ambiguity tasks:
- recurring review reminders / scheduled scans
- issue template population
- label application by type / priority / area
- dependency link creation when declared
- stale-claim detection
- PR template enforcement
- required status checks
- branch protection
- closeout checklist enforcement
- release note drafting
- secret scanning

### Leave manual

Judgment-heavy tasks:
- approving proposed work
- scoping/splitting issues
- deciding whether issues should bundle or serialize
- evaluating blast radius
- deciding high-risk production promotion timing
- manually verifying external-provider behavior

### Hybrid

Best pattern:
- agent drafts
- human approves
- automation enforces
- CI verifies
- maintainer decides risky promotion

---

## 17. Branch protection and repository controls

Recommended repository settings:

### For production branch
- no direct pushes
- PR required
- required passing checks
- required review(s)
- stale review dismissal on new commits
- auto-merge allowed only with checks

### For integration branch
- no force pushes
- required checks
- lighter review rules if desired

### Supporting files to add over time
- PR template
- issue templates
- CODEOWNERS
- merge strategy policy
- security policy / disclosure route

---

## 18. Anti-patterns and failure modes

Do **not** allow:
- implementation without approval
- “grab bag” improvement PRs touching unrelated areas
- two agents editing the same hotspot without declared dependency
- claim by branch existence only
- stale claims with no expiry
- closing issues on PR creation or integration merge alone
- CI pass used as a substitute for required manual checks
- unrelated work bundled just to reduce admin overhead
- verification evidence living only in chat
- direct pushes to production branch
- long-lived drifting feature branches
- vague issues like “clean up translator”
- hidden follow-up work not broken into new issues

---

## 19. Suggested issue / PR vocabulary

### Status labels
- `status:proposed`
- `status:approved`
- `status:ready`
- `status:claimed`
- `status:blocked`
- `status:in-review`
- `status:ready-to-merge`
- `status:merged-to-integration`
- `status:verified-on-integration`
- `status:merged-to-production`
- `status:verified-on-production`
- `status:done`

### Type labels
- `type:security`
- `type:performance`
- `type:reliability`
- `type:code-health`
- `type:test`
- `type:observability`
- `type:docs`
- `type:dx`
- `type:feature`

### Area labels
- `area:translator`
- `area:config`
- `area:tests`
- `area:infra`
- `area:scripts`
- `area:docs`

### Priority labels
- `priority:high`
- `priority:medium`
- `priority:low`

---

## 20. Repo-specific appendix template

Every repo using this document should append:

- branch strategy
- worktree policy
- environment / slot policy
- CI-enforced checks
- manual verification commands
- issue templates in use
- PR template requirements
- branch protection settings
- critical hotspot files / subsystems

---

## Repo-specific appendix: AI Gateway

### Branch strategy

```text
feat/* -> PR -> main
```

### Environment strategy

- stable stack: port 4000
- isolated dev stacks: `./dev-env.sh start <slot>`
- slot 0 reserved for stable stack
- all feature work must happen in a worktree off `main`

### Current machine-enforced checks

- ruff lint / format for translator
- YAML validation for `litellm-config.yaml`
- hardcoded API key detection
- translator unit tests

### Current manual verification

- `./dev-env.sh test <slot>`
- `./cliproxy-setup.sh health`
- representative E2E checks:
  - Claude
  - Gemini
  - GPT

### Current useful commands

- `./dev-env.sh start <slot>`
- `./dev-env.sh stop <slot>`
- `./dev-env.sh test <slot>`
- `./dev-env.sh list`
- `./cliproxy-setup.sh health`
- `./cliproxy-setup.sh test <model>`
- `./cliproxy-setup.sh quota-summary`
- `./cliproxy-setup.sh sync-models`

### Current issue body pattern worth preserving

- Problem
- Actions
- Files

### Recommended additions for this repo

- issue templates
- PR template
- CODEOWNERS
- branch protection for `main`
- explicit status labels for claims and verification stages
