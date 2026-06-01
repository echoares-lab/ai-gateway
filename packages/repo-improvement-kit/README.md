# Repo Improvement Kit

Portable governance/docs package for multi-agent repository improvement workflows.

The default workflow assumes feature branches or worktrees are created from
`main`, tested in isolation, and merged back to `main` through pull requests.
Repos that use a separate integration branch can document that in the
repo-specific appendix.

## How it fits together

The kit separates portable process from repo-specific operating details.

- Portable (lives in this package, copied as-is):
  - `REPO_IMPROVEMENT_WORKFLOW.md` — the process rules.
  - `REPO_IMPROVEMENT_APPENDIX.template.md` — placeholders for branch/env/test details.
  - `AGENT_DISPATCH.template.md` — placeholders for the agent prompt that drives PR processing.
  - `.github/*` — issue templates, PR template, CODEOWNERS, branch protection policy.

- Repo-specific (generated from templates into the target repo root):
  - `REPO_IMPROVEMENT_APPENDIX.md` — concrete branch policy, environment, test commands, hotspot files.
  - `AGENT_DISPATCH.md` — concrete agent prompt with repo slug, paths, priorities, commands.

### Install flow

1. Copy this package into the target repo.
2. Move `.github/*` under the repo's `.github/`.
3. Keep `REPO_IMPROVEMENT_WORKFLOW.md` at the repo root (or `docs/process/`).
4. Generate the repo-specific docs from templates:
   - `REPO_IMPROVEMENT_APPENDIX.template.md` -> `REPO_IMPROVEMENT_APPENDIX.md`
   - `AGENT_DISPATCH.template.md` -> `AGENT_DISPATCH.md`
5. Fill placeholders in each generated file.
6. Replace owners in `CODEOWNERS` and the security URL in `ISSUE_TEMPLATE/config.yml`.
7. Apply branch protection per `BRANCH_PROTECTION_POLICY.md`.
8. Create the `status:*`, `type:*`, `area:*`, `priority:*` labels.

### Per-change operating flow

1. An approved issue exists with `status:ready`.
2. The agent reads `REPO_IMPROVEMENT_WORKFLOW.md` and `REPO_IMPROVEMENT_APPENDIX.md`, then runs the prompt in `AGENT_DISPATCH.md`.
3. The agent claims the issue (assignee + unique `Claim-ID` comment + `status:claimed`).
4. The agent works in a feature worktree/branch from `main` and runs required tests from the appendix.
5. The agent opens a PR, enables auto-merge, and waits for CI.
6. Post-merge: run smoke/health checks from the appendix, post a closeout comment, clean up.

### Update rules

- Process rule changes -> edit `REPO_IMPROVEMENT_WORKFLOW.md`.
- Environment, branch, or test command changes -> edit `REPO_IMPROVEMENT_APPENDIX.md`.
- Agent prompt behavior changes -> edit `AGENT_DISPATCH.md`.
- Do not embed repo-specific commands or owners in the portable workflow or templates.

---

## What this kit contains

- `REPO_IMPROVEMENT_WORKFLOW.md` — reusable process for discovery, approval, issue creation, claiming, execution, merge, and promotion
- `REPO_IMPROVEMENT_APPENDIX.template.md` — repo-specific appendix template for branch, environment, and verification details
- `AGENT_DISPATCH.template.md` — portable agent prompt template for claim → implement → PR → auto-merge → closeout
- `.github/ISSUE_TEMPLATE/repo-improvement.yml` — standardized improvement issue template
- `.github/ISSUE_TEMPLATE/config.yml` — issue-template config and security reporting link placeholder
- `.github/pull_request_template.md` — PR checklist with tests, dependencies, and rollout notes
- `.github/CODEOWNERS` — sample CODEOWNERS file
- `.github/BRANCH_PROTECTION_POLICY.md` — branch protection settings to apply in GitHub UI
- `ADOPTION_GUIDE.md` — how to customize this kit for another repo

## How to use in another repo

1. Copy the entire `packages/repo-improvement-kit/` folder into the target repo.
2. Move the `.github/*` contents into that repo’s `.github/` directory.
3. Keep `REPO_IMPROVEMENT_WORKFLOW.md` at repo root (or docs/process/).
4. Copy `REPO_IMPROVEMENT_APPENDIX.template.md` to `REPO_IMPROVEMENT_APPENDIX.md` and fill it in for the target repo.
5. Copy `AGENT_DISPATCH.template.md` to `AGENT_DISPATCH.md` and fill in repo-specific commands, paths, and priorities.
6. Replace placeholder owners in `CODEOWNERS`.
7. Replace the placeholder security disclosure URL in `.github/ISSUE_TEMPLATE/config.yml`.
8. Configure GitHub branch protection manually using `BRANCH_PROTECTION_POLICY.md`.
9. Add labels described in the workflow doc (`status:*`, `type:*`, `area:*`, `priority:*`).

## Deploying the kit to other repos

Pick the option that matches how tightly you want to track upstream changes.

### Option A — One-time manual copy

Simplest. Use when the target repo will diverge or maintain its own variant.

```bash
SRC=/path/to/this-repo/packages/repo-improvement-kit
DST=/path/to/target-repo

cp -R "$SRC"/.github                                 "$DST"/.github
cp "$SRC"/REPO_IMPROVEMENT_WORKFLOW.md               "$DST"/REPO_IMPROVEMENT_WORKFLOW.md
cp "$SRC"/REPO_IMPROVEMENT_APPENDIX.template.md      "$DST"/REPO_IMPROVEMENT_APPENDIX.md
cp "$SRC"/AGENT_DISPATCH.template.md                 "$DST"/AGENT_DISPATCH.md
```

Then fill in placeholders, owners, and the security URL as listed in
`ADOPTION_GUIDE.md`. Commit the result on a feature branch and open a PR.

### Option B — Vendored copy with a sync script

Use when you want to receive upstream updates but keep generated files local.

1. Vendor the kit at a stable path in the target repo:
   ```bash
   mkdir -p tools/repo-improvement-kit
   cp -R "$SRC"/. tools/repo-improvement-kit/
   ```
2. Add a sync script (target repo) that:
   - rsyncs `tools/repo-improvement-kit/` from a known upstream location;
   - copies `REPO_IMPROVEMENT_WORKFLOW.md` and `.github/*` over;
   - does **not** overwrite `REPO_IMPROVEMENT_APPENDIX.md` or `AGENT_DISPATCH.md`.
3. Re-run the sync script when upstream changes; review the diff in a PR.

### Option C — Git subtree

Use when you want versioned upstream tracking without submodules.

```bash
git remote add improvement-kit <upstream-kit-repo-url>
git subtree add  --prefix tools/repo-improvement-kit improvement-kit main --squash

# later, to pull updates:
git subtree pull --prefix tools/repo-improvement-kit improvement-kit main --squash
```

Generated files (`REPO_IMPROVEMENT_APPENDIX.md`, `AGENT_DISPATCH.md`) still live
at the target repo root, not inside the subtree.

### Option D — Git submodule

Use when you want an explicit pinned reference to the upstream kit.

```bash
git submodule add <upstream-kit-repo-url> tools/repo-improvement-kit
git submodule update --init --recursive
```

Generated files are produced from the submodule's templates and committed to
the target repo root.

### After any deployment option

1. Generate repo-specific docs (see "How to use in another repo" above):
   - `REPO_IMPROVEMENT_APPENDIX.md`
   - `AGENT_DISPATCH.md`
2. Replace placeholders in `CODEOWNERS` and `ISSUE_TEMPLATE/config.yml`.
3. Apply branch protection per `BRANCH_PROTECTION_POLICY.md`.
4. Create labels: `status:*`, `type:*`, `area:*`, `priority:*`.
5. Reference the kit from the target repo's `AGENTS.md` and `CLAUDE.md` (or
   equivalent agent instruction files) so agents read the workflow, appendix,
   and dispatch prompt before acting.

### Updating an existing deployment

- Process changes (`REPO_IMPROVEMENT_WORKFLOW.md`, `.github/*`): re-copy from
  the kit, review the diff, open a PR.
- Repo-specific changes (`REPO_IMPROVEMENT_APPENDIX.md`, `AGENT_DISPATCH.md`):
  edit in place in the target repo; do not push back to the kit.
- Template changes (`*.template.md`): re-copy as a starting point, then port
  any improvements into the generated files by hand.

---

## Suggested repo-specific edits

- branch strategy (`main -> feature worktree/branch -> PR -> main` by default)
- environment / staging model
- test commands
- owner handles
- CI check names
- security disclosure URL

See `ADOPTION_GUIDE.md` for a checklist.
