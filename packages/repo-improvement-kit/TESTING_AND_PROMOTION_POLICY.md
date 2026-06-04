# Testing and Promotion Policy

Portable policy for gating changes before they reach production. Pair this document
with `REPO_IMPROVEMENT_WORKFLOW.md` (process) and `REPO_IMPROVEMENT_APPENDIX.md`
(repo-specific commands and CI job names).

---

## 1. Four promotion gates

| Gate | Purpose | Typical timing | Blocks PR merge? |
|------|---------|----------------|------------------|
| **A** | Lint, schema/config validation, fast unit tests (no external providers) | Every commit / PR | Yes |
| **B** | Deterministic integration against canned or mock dependencies; skips must be disabled | Every PR touching runtime code | Yes |
| **C** | Real external dependencies (OAuth, live APIs, staging); smoke on PR, full matrix on schedule | Label, schedule, or maintainer trigger | No (unless repo policy says otherwise for high-risk paths) |
| **D** | Post-merge verification on the stable/production channel | After merge to trunk | Manual; recorded in closeout |

**Rules**

- Gate C passing is **necessary but not sufficient** for high-risk changes (`type:security`, auth, routing, provider config, deployment).
- Gate D is required before closing issues whose target is production behavior.
- Failed gates must be recorded in the PR or issue (`status:ci-failed` or equivalent), with the command and environment used.

---

## 2. Risk-tiered test matrix

PR checklists should match risk, not run everything on every change.

| Risk | Examples | Gate A | Gate B | Gate C | Gate D |
|------|----------|--------|--------|--------|--------|
| **Low** | docs, templates, non-runtime tooling | required | optional | no | no |
| **Medium** | internal logic, test refactors, scripts | required | required | no | no |
| **High** | auth, routing, provider config, compose/infra | required | required | smoke (label or maintainer) | post-merge smoke on stable |

Declare risk level in every PR (`Risk / rollback` section).

---

## 3. Parallel agent isolation (one claim = one triple)

Each active claim must own a unique **isolation triple**:

| Resource | Rule |
|----------|------|
| **Git directory** | One feature worktree per claim; never edit the stable checkout for feature work |
| **Git branch** | `feat/<issue>-<slug>` from trunk; rebase before merge; delete branch and worktree after closeout |
| **Runtime slot** | One dev/test slot per claim; slot 0 (or equivalent stable slot) reserved for production-like traffic |

**Mock vs real stack**

- Use the mock/canned stack for Gate B during development.
- Start a real-provider stack only for Gate C or manual provider verification.

**Claim comment must include:** `Claim-ID`, branch, worktree path, slot (if applicable), mock vs real.

---

## 4. Merge and versioning

- **Default trunk:** `main` only. Document any optional integration branch in the repo appendix.
- **Merge method:** pick one per repo (squash for agent-sized issues is recommended); document in appendix.
- **Versioning:** tag trunk at production milestones; pin runtime images by digest where possible; treat runtime config like code (PR + Gate B).
- **Closeout record:** merge SHA, gates run (A/B/C/D), and whether verified on staging only or production (`verified-on-production`).

---

## 5. Evidence in artifacts

- Test commands, slot, and results belong in PR test plan and issue closeout — not only in chat.
- When a gate fails, paste the failing command output or CI job link in the issue thread.

---

## 6. Repo specialization (appendix)

Each repo appendix must define:

1. Gate A/B/C/D commands (copy-paste ready)
2. CI job names mapped to gates (for branch protection)
3. Worktree / branch / slot policy (or “single clone + feature branch” if no runtime collision)
4. Risk tiers and paths that trigger Gate C
5. Post-merge Gate D commands on the stable channel

### Archetype reference

| Archetype | Gate B | Gate C | Isolation |
|-----------|--------|--------|-----------|
| Library (no runtime) | unit + contract tests | none | branch only |
| Single-service API | mock HTTP upstream | staging smoke | one test env URL |
| Infra / gitops | validate / plan dry-run | apply to staging | branch + separate state workspace |
| Multi-service gateway | mock compose stack | real OAuth / providers | worktree + slot |

See `ADOPTION_GUIDE.md` for kit installation steps.
