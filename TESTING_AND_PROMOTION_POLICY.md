# Testing and Promotion Policy

Portable policy — canonical copy lives in
`infra/repo-improvement/TESTING_AND_PROMOTION_POLICY.md`.

Repo-specific gate commands and CI job names: see `REPO_IMPROVEMENT_APPENDIX.md` and `docs/TESTING.md`.

---

## 8. Epic-Based Development and Release Policy

To ensure stability, manage complexity, and enable phased releases, all significant feature development (epics) must adhere to the following workflow:

### Worktree Usage
All feature development for an epic must occur within an isolated Git worktree. This prevents interference with the stable `main` branch and allows seamless switching between different epic contexts. Refer to `WORKTREES.md` for detailed instructions on creating and managing worktrees.

### Branching Strategy
Feature branches (`feat/<epic-feature>`) should always branch off `main`. If a feature depends on another unmerged feature, stacked branches are permitted (e.g., `feat/<epic-2-subfeature>` branching from `feat/<epic-2-main-feature>`). However, direct merges between feature branches are discouraged. All feature branches must eventually rebase onto `main` before merging.

### Epic Milestones and Merging to Main
Merges to `main` (and subsequent deployment to `production`) are strictly reserved for the completion of a logical milestone, typically an entire epic. This means:
*   **No Partial Epic Merges:** Individual sub-features of an epic should NOT be merged directly to `main` if the epic is not yet complete. They should remain in their respective feature branches, potentially stacked.
*   **Milestone Validation:** Before merging an epic-completing branch to `main`, the entire epic must be thoroughly validated, including all Gates (A, B, C, and D) as applicable.
*   **PR from Working Branch/Worktree:** All pull requests targeting `main` must originate from a dedicated working branch or worktree, ensuring a clear audit trail and CI validation.

### Switching Between Epics
Developers (including AI agents) must use `git worktree` to switch between different epic development contexts. This ensures that:
*   Each epic's environment is isolated.
*   Dependencies are managed cleanly.
*   The `main` branch remains untouched and stable.

### Post-Epic Merge Validation (Gate D)
Upon merging an epic to `main`, the stability of the production environment must be validated as per Gate D procedures. Any regressions found must be addressed immediately with a hotfix.

---

