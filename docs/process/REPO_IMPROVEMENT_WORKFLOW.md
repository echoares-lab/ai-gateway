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

5. **Production must be protected.**
   Changes should move through a feature worktree or branch, pass required checks, and merge through a protected PR.

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
- one area label (`area:gateway-engine`, `area:tests`, etc.)
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
- `merged-to-staging`
- `verified-on-staging`
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

### A claim is valid only if all 4 happen

1. The issue is assigned.
2. A “start work” comment is posted.
3. The start-work comment includes a unique `Claim-ID` tag.
4. The status changes to `claimed` or `in-progress`.

### Claim identity rule

The `Claim-ID` must uniquely identify the agent session, not just the GitHub
account. This matters when multiple agents share the same GitHub user. Use a
stable, human-readable format:

```text
Claim-ID: <agent>-<host-or-run-id>-<utc-timestamp>
```

Examples:
- `Claim-ID: codex-ai-gateway-20260601T213000Z`
- `Claim-ID: claude-run-78241-20260601T213000Z`

When a claim is transferred, stale, or reclaimed, reference the previous
`Claim-ID` explicitly in the issue thread.

### Required start-work comment format

Every claim comment must include:
- agent name / owner
- unique `Claim-ID`
- branch name
- worktree name/path (if applicable)
- environment slot (if applicable)
- dependency issues included in the claim
- expected scope

### Example

```text
Starting work on #123.
Claim-ID: codex-ai-gateway-20260601T213000Z
Claiming: #123, #124
Branch: feat/cache-auth-key
Worktree: /home/dev/worktrees/ai-gateway-cache-auth-key
Slot: 2
Scope: gateway-engine cache key + tests
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
- `area:gateway-engine`
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

### One agent, one isolation unit

For repos with dev slots (see appendix):

- **One issue = one agent = one worktree + one branch + one slot**
- Check the slot registry (`./dev-env.sh list`) before starting a stack; never use the stable slot (0)
- `Claim-ID` in the start-work comment must be unique per agent session, not per GitHub user

### Rebase and PR stacking

When issues share a subsystem or hotspot, prefer a **shallow dependency graph**:

1. **Independent work** — branch from `main`, PR base `main`.
2. **Open dependency, stable PR** — branch from the dependency feature branch; PR base that branch (stacked PR). Implement only after confirming the dependency issue is claimed and its PR is CI-green.
3. **Dependency merged** — in the dependent worktree:
   ```bash
   git fetch origin
   git rebase origin/main
   # resolve conflicts, make test-fast (or repo equivalent), then:
   git push --force-with-lease
   ```
   Update the PR base to `main` if GitHub still shows the old base branch.

**Dependency polling before claim or implementation:**

```bash
gh issue view <dep> --json state,closed
gh pr view <dep-pr> --json state,mergedAt,statusCheckRollup
```

Do not merge a dependent PR until its `Depends on` issues are closed/merged unless the issue explicitly allows otherwise.

**CI flake handling:** If required CI fails on infrastructure (runner timeout, transient mock stack failure) but local Gate B passes, record local `make test-mock` (or appendix equivalent) in the PR comment before retrying CI or requesting merge.

---

## 10. Branch, worktree, and environment workflow

General pattern:

```text
main
  → feature branch/worktree
  → pull request
  → main
```

### Recommended execution flow

1. Create feature branch or worktree from `main`
2. Place the worktree in the repo appendix's **worktrees root** (outside the stable checkout — not a sibling folder, not inside the repo tree)
3. Start isolated dev/test environment if needed
4. Implement in small increments
5. Run fast tests continuously
6. Open PR back to `main`
7. Run CI + required manual checks
8. Merge only after required approval and verification

### Rule

Never develop directly in a live or stable worktree if the repo has a production-like local stack.
Repos that use a separate integration branch should document that repo-specific policy in the appendix.

Parallel-agent isolation (worktree + branch + slot): see `TESTING_AND_PROMOTION_POLICY.md` section 3.

### Worktree cleanup (required closeout)

Cleanup happens **after** the PR merges to the target branch and post-merge verification
(Gate D or appendix equivalent) — not when the PR is opened and not before rebase/fix
pushes are finished.

**Standard sequence** (paths from repo appendix):

```bash
./dev-env.sh stop <slot>
cd <stable-repo-path>
git worktree remove <worktrees-root>/ai-gateway-<feature>
git branch -d feat/<feature>
git worktree list    # verify only stable checkout remains
```

**If removal fails:** commit or stash uncommitted work in the feature worktree, ensure
the dev stack is stopped, retry `git worktree remove`; use `git worktree prune` for stale
metadata. `--force` is a last resort when the directory is intentionally discarded.

**Coordinator responsibility:** Parent or dispatching agents must confirm cleanup before
marking an epic or multi-issue session done — no orphaned worktrees, no occupied slots,
closeout comment posted on each issue.

**Stable checkout hygiene:** The stable worktree must stay clean for `git pull` and
post-merge smoke tests. Do not use it for feature edits.

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

### Manual merge fallback

Auto-merge may be disabled by branch protection or repository settings. When
`gh pr merge --auto` does not queue a merge despite green required checks:

1. Confirm no blocking review comments remain.
2. Rebase onto latest `main` if the base branch moved since the last CI run.
3. Merge explicitly: `gh pr merge <num> --merge` (or squash if repo policy prefers).
4. Record in the PR or issue thread that merge was manual.

Rebase before merge when `main` has advanced since the PR last passed CI — especially
for stacked PRs whose dependency just landed.

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
- whether the change is verified on staging only or on production too
- worktree/slot cleanup confirmed (`git worktree list`, slot released)

### Rule

`merged-to-staging` is not the same as `done`.
If the issue target is production behavior, close after production verification.

---

## 15. Release channels, versioning, and staging

Versioning and staged promotion are key to avoiding regressions.

### Recommended release channels

- feature / worktree
- staging / integration branch/environment if the repo uses one
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
- `channel:staging`
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

### For optional integration branch
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
- closing issues on PR creation or staging merge alone
- CI pass used as a substitute for required manual checks
- unrelated work bundled just to reduce admin overhead
- verification evidence living only in chat
- direct pushes to production branch
- long-lived drifting feature branches
- vague issues like “clean up gateway-engine”
- hidden follow-up work not broken into new issues
- removing worktrees or stopping dev stacks before PR merge
- dirty stable checkout blocking post-merge `git pull`
- two agents sharing a dev slot without documented handoff

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
- `status:merged-to-staging`
- `status:verified-on-staging`
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
- `area:gateway-engine`
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

## 20. Repo-specific appendix

This repo keeps repository-specific details in `REPO_IMPROVEMENT_APPENDIX.md`
next to this document. Do not embed repo-specific commands, branch names,
owners, or provider details in the reusable workflow.

The appendix should define:

- branch strategy
- worktree policy
- environment / slot policy
- CI-enforced checks
- manual verification commands
- issue templates in use
- PR template requirements
- branch protection settings
- critical hotspot files / subsystems
