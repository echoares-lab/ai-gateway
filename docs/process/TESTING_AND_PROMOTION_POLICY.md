# Testing and Promotion Policy

Portable policy — canonical kit copy lives in
`packages/repo-improvement-kit/TESTING_AND_PROMOTION_POLICY.md`.

Repo-specific gate commands and CI job names: see
`docs/process/REPO_IMPROVEMENT_APPENDIX.md` and `docs/TESTING.md`.

---

## Gate summary (this repo)

| Gate | Meaning | Blocks merge? |
|------|---------|---------------|
| **A** | Lint + unit (`make lint`, `make test-unit`) | Yes |
| **B** | In-memory mock integration (`make test-mock`) | Yes (when runtime paths change) |
| **C** | Real-provider E2E (`make test-e2e` / `run-e2e`) | **No** — opt-in / advisory |
| **D** | Post-merge stable smoke | Advisory |

**Day-to-day rule:** ship **atomic PRs** that pass Gate A (+ B when applicable). Do not block small, complete PRs waiting for an entire epic to finish.

**Epic batching (advisory):** For large multi-issue epics, prefer stacking or merging milestone-complete slices when dependencies require it — but atomic, CI-green PRs to `main` are the default and are encouraged.

---

## 8. Epic-Based Development and Release Policy

To ensure stability, manage complexity, and enable phased releases, significant feature development (epics) should adhere to the following workflow. This section is **guidance for coordination**, not a ban on merging completed child issues.

### Worktree Usage
All feature development for an epic must occur within an isolated Git worktree. This prevents interference with the stable `main` branch and allows seamless switching between different epic contexts. Refer to `docs/process/WORKTREES.md` for detailed instructions on creating and managing worktrees.

### Branching Strategy
Feature branches (`feat/<epic-feature>`) should always branch off `main`. If a feature depends on another unmerged feature, stacked branches are permitted (e.g., `feat/<epic-2-subfeature>` branching from `feat/<epic-2-main-feature>`). However, direct merges between feature branches are discouraged. All feature branches must eventually rebase onto `main` before merging.

### Epic Milestones and Merging to Main
- **Default:** merge atomic, reviewable PRs when their acceptance criteria are met and required gates pass.
- **Avoid half-done surfaces:** do not merge PRs that leave the request path broken or undocumented mid-change; prefer vertical slices.
- **Milestone validation:** when closing an epic, confirm applicable Gates A/B (and C/D for high-risk) across the epic scope — not only the last PR.
- **PR from working branch/worktree:** all pull requests targeting `main` must originate from a dedicated working branch or worktree.

### Switching Between Epics
Developers (including AI agents) must use `git worktree` to switch between different epic development contexts. This ensures that:
*   Each epic's environment is isolated.
*   Dependencies are managed cleanly.
*   The `main` branch remains untouched and stable.

### Post-Epic Merge Validation (Gate D)
Upon merging high-risk or epic-completing work to `main`, validate production stability per Gate D. Any regressions found must be addressed immediately with a hotfix.
