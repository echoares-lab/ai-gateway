# CLIProxy Upstream-Patch Migration and Dependency Updates — Implementation Plan

> **For agentic workers:** Execute one atomic GitHub child per claim, branch,
> external worktree, and PR. Do not claim parent epic #413.

**Goal:** Reset CLIProxyAPI to upstream plus two quota patches, gate immutable
cliproxy candidates through staging, and establish repeatable dependency update
and rollback operations.

**Architecture:** CLIProxyAPI owns weekly upstream reconstruction and Nexus
candidate publication. ai-gateway owns dependency discovery and promotion
orchestration. k3s-01 remains authoritative for staging and production image
digests.

**Design:** `docs/superpowers/specs/2026-07-17-cliproxy-upstream-patch-dep-updates-design.md`

## Global constraints

- Parent #413 is coordination-only.
- Never edit or test from the stable port-4000 checkout.
- Keep the CLIProxy local stack to two quota commits or fewer.
- Never auto-merge cliproxy, LiteLLM, gateway-engine, or major dependency
  updates.
- Production pins immutable digests, not candidate or `latest` tags.
- Never copy staging OAuth state into production.
- Record old/new digests and rollback commands before promotion.
- Run live provider and cluster gates outside Cursor Cloud as required by the
  repository testing appendix.

## Dependency graph

```text
#414
├── CLIProxyAPI #12 ──> CLIProxyAPI #13 ──> CLIProxyAPI #11
├── #415 ───────────────────────────────────────┐
└── #416 ──> #417                              │
CLIProxyAPI #13 + #414 (+ #415 preferred) ──> #418 ──> #419
```

CLIProxyAPI #11 and ai-gateway #415/#416 may proceed in parallel when their
hard dependencies are merged. Serialize changes to the same promotion workflow
or k3s overlay.

## Task 0: Promote the roadmap and freeze decisions (#414)

**Files:** `docs/ROADMAP.md`, `docs/FEATURE_CANDIDATES.md`, this plan, and the
design document.

- [ ] Claim #414 and change its lifecycle label to `status:claimed`.
- [ ] Add epic #413 and every child to Roadmap Next with explicit order and
  dependencies.
- [ ] Remove the matching item from unapproved candidate inventory and retain a
  promoted-history entry.
- [ ] Review all 11 fork-commit dispositions against #413 and the frozen fork
  lineage.
- [ ] Run:

  ```bash
  test -f docs/superpowers/specs/2026-07-17-cliproxy-upstream-patch-dep-updates-design.md
  test -f docs/superpowers/plans/2026-07-17-cliproxy-upstream-patch-dep-updates.md
  rg -n '#413|CLIProxy upstream' docs/ROADMAP.md docs/FEATURE_CANDIDATES.md
  git diff --check
  ```

- [ ] Commit `docs(ops): plan cliproxy upstream patch migration`.
- [ ] Open a draft PR to `main` linking #414. Do not implement later tasks in
  this branch.

## Task 1: Reset the CLIProxyAPI fork (#12)

**Repository:** `echoares-lab/CLIProxyAPI`  
**Depends on:** #414 merged  
**Expected files:** fork branch/history plus any CI references that name its
base; no ai-gateway runtime changes.

- [ ] Claim #12 and capture the current `main`, upstream, and production
  `6cf6e68` SHAs.
- [ ] Fetch canonical upstream and generate the ordered 11-commit comparison:

  ```bash
  git fetch upstream main
  git log --reverse --format='%H %s' upstream/main..main
  git diff --stat upstream/main...main
  ```

- [ ] Copy the old SHA for each commit into the design decision table in the
  CLIProxyAPI PR description and verify all 11 map to exactly one row.
- [ ] Create the reset branch at the selected upstream SHA. Do not cherry-pick
  auth-hardening or batch-credential commits.
- [ ] Run upstream Go tests, lint/static checks, and image build commands
  defined by CLIProxyAPI.
- [ ] Prove the branch has zero local commits before quota re-port:

  ```bash
  test "$(git rev-list --count upstream/main..HEAD)" -eq 0
  ```

- [ ] Commit only CI/provenance adjustments required by the reset, if any, and
  open the CLIProxyAPI PR. Record the old fork head as a rollback tag.

## Task 2: Re-port the quota stack (#13)

**Repository:** `echoares-lab/CLIProxyAPI`  
**Depends on:** CLIProxyAPI #12  
**Patch limit:** two commits.

- [ ] Claim #13 on the reset branch.
- [ ] Add failing tests for normalized quota windows, provider-specific
  refresh, and `fresh|unsupported|missing|error` partial-state semantics.
- [ ] Reimplement the quota foundation as one focused commit.
- [ ] Add failing live-contract tests, then implement live refresh and explicit
  partial statuses as the second focused commit.
- [ ] Confirm no batch or superseded auth routes returned:

  ```bash
  git log --oneline upstream/main..HEAD
  test "$(git rev-list --count upstream/main..HEAD)" -le 2
  ```

- [ ] Run the complete CLIProxyAPI test suite and build a candidate image.
- [ ] Against that candidate, run ai-gateway quota contract tests and staging
  deep-smoke quota assertions.
- [ ] Commit as `feat(quota): re-port quota status foundation` and
  `feat(quota): re-port live quota contract`; open the PR with old/new contract
  evidence.

## Task 3: Add weekly upstream tracking and Nexus candidates (#11)

**Repository:** `echoares-lab/CLIProxyAPI`  
**Depends on:** #12 and #13.

- [ ] Claim #11 and add a weekly scheduled workflow with manual dispatch.
- [ ] Fetch upstream, reconstruct/rebase the two-patch stack, and fail on
  conflicts or patch count greater than two.
- [ ] Run Go tests, quota tests, static checks, image build, and image scan.
- [ ] Publish only after all checks pass. Tag the candidate with upstream SHA
  and patch-head SHA and capture its immutable Nexus digest.
- [ ] Emit a PR or issue containing commit ranges, release notes, checks,
  candidate digest, prior digest, and rollback target.
- [ ] Add workflow tests or a safe dry run that proves a failed rebase/test does
  not publish.
- [ ] Commit `ci: track CLIProxy upstream weekly`.

## Task 4: Include cliproxy in the promotion gate (#415)

**Repository:** `ai-gateway`  
**Depends on:** #414; soft dependency on CLIProxyAPI #11  
**Files:** `.github/workflows/promote-k3s-images.yml`,
`scripts/k3s/promote_k3s_images.py`, related tests and CICD docs.

- [ ] Claim #415 and serialize edits to the promote workflow hotspot.
- [ ] Write failing offline tests for required cliproxy candidate resolution,
  digest pin output, and rejection of a missing/mutable candidate.
- [ ] Accept CLIProxyAPI repository dispatch or explicit workflow input while
  preserving manual emergency behavior.
- [ ] Resolve the candidate to a digest before staging and pass both
  gateway-engine and cliproxy pins into the k3s-01 PR path.
- [ ] Require successful staging deep-smoke `--full` before a production pin
  PR; do not alter the semantics of explicit `skip_deep_smoke`.
- [ ] Run YAML validation, promote-script unit tests, relevant Gate A/B tests,
  and one dry-run against a candidate.
- [ ] Commit `ci(ops): gate cliproxy image promotion`.

## Task 5: Inventory dependencies and configure Renovate (#416)

**Repository:** `ai-gateway`  
**Depends on:** #414  
**Files:** Renovate configuration, compose/config inventory, and ops/CICD docs.

- [ ] Claim #416 and inventory image references in compose files, environment
  defaults, scripts, docs, and k3s handoff configuration.
- [ ] Record owner, current version/tag/digest, source, update mechanism, risk,
  migration surface, gate, and rollback target for every component in the
  design inventory.
- [ ] Add Renovate configuration and validate it with Renovate's config
  validator or dry-run.
- [ ] Configure high/medium/low risk labels and PR checklists. Disable
  auto-merge for high risk and all major updates.
- [ ] Keep Langfuse web/worker synchronized; separate ClickHouse, MinIO, and
  database majors for migration review.
- [ ] Ensure all floating runtime references are either pinned or explicitly
  documented as staging-only discovery inputs.
- [ ] Run compose/YAML validation and repository config tests.
- [ ] Commit `chore(ops): inventory and automate dependency updates`.

## Task 6: Publish the per-component update playbook (#417)

**Repository:** `ai-gateway`  
**Depends on:** #414 and #416; soft dependency on #415  
**Files:** `docs/ops/DEPENDENCY_UPDATES.md`, `docs/ops/RUNBOOK.md`, and CICD docs.

- [ ] Claim #417 and write one executable section per inventory component.
- [ ] For each component, document update intake, release-note review, exact
  pre-merge gates, staging promote path, production verification, and rollback.
- [ ] Include DB/image compatibility rules for LiteLLM, Langfuse, ClickHouse,
  Redis, and Postgres.
- [ ] Add a dependency-update PR checklist requiring old/new digest, migration
  notes, evidence, previous pin, and rollback command.
- [ ] Link the playbook from the runbook and staging/production CICD docs.
- [ ] Validate links and commands, then commit
  `docs(ops): add dependency update and rollback playbook`.

## Task 7: Cut over cliproxy through staging and production (#418)

**Repositories:** `ai-gateway` and `k3s-01`  
**Depends on:** CLIProxyAPI #13 and #414; #415 preferred  
**Risk:** High.

- [ ] Claim #418 and capture the current production/staging digest, Argo
  revisions, pod image IDs, and OpenBao auth archive reference.
- [ ] Resolve the upstream-plus-quota candidate to its Nexus digest.
- [ ] Pin staging to the candidate and wait for Argo sync/readiness.
- [ ] Run:

  ```bash
  ./scripts/ops/deep-smoke.sh --env staging --full
  ```

- [ ] Verify `/admin/quota/status` against the documented OpenAPI contract and
  confirm the auth PVC remains usable.
- [ ] Exercise rollback to N-1, rerun staging `--full`, restore N, and rerun
  staging `--full`. Attach all three results to #413.
- [ ] Promote the exact tested digest via the gated k3s-01 PR.
- [ ] After production sync, verify image ID, health, claude/gpt/gemini model
  smokes, and quota summary. Record Gate D evidence and rollback pin.
- [ ] Update ai-gateway's compose default only to the validated immutable
  version/digest as scoped by #418.

## Task 8: Archive obsolete management and fork surfaces (#419)

**Depends on:** successful #418 production verification.

- [ ] Claim #419 only after cutover closes.
- [ ] Confirm CPA-Manager replaces the standalone Management-Center in current
  deployment and operator workflows.
- [ ] Remove stale documentation references and mark/archive the obsolete
  repository through an authorized maintainer operation.
- [ ] Inventory stale fork branches. Delete or mark them rollback-only while
  preserving immutable rollback tags and SHAs.
- [ ] Update instructions that still build from the old fork `dev` branch.
- [ ] Run docs/link checks and commit
  `chore(ops): retire obsolete cliproxy fork surfaces`.

## Epic closeout

- [ ] Confirm every atomic child PR merged in dependency order.
- [ ] Record final upstream SHA, two quota patch SHAs, Nexus digest, staging and
  production Argo revisions, and previous digest.
- [ ] Link the successful N → N-1 → N rollback drill and final Gate D evidence.
- [ ] Confirm Renovate inventory and playbook cover every runtime component.
- [ ] Verify all worktrees and dev slots are cleaned up after merge.
- [ ] Post closeout on #413 and move the roadmap entry to Completed.
