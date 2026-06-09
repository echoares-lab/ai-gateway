# Unmerged Features Backlog

Audit date: 2026-06-09. Evaluated all local worktrees and remote branches against `main` (`001c5d9`).
Risk tiers: **low** (docs/small fix), **medium** (isolated feature), **high** (large refactor / stale base).

## Applied in `chore/consolidate-unmerged-work`

| Source | Change | Risk |
|--------|--------|------|
| `fix/dev-env-list-cmd` | Removed duplicate `cmd_list()` definition in `dev-env.sh` (function was defined twice) | low |
| `origin/feat/final-fix` (partial) | Integration client profiles (`claude.yaml`, `cursor.yaml`) + wired `client_detector` in catch-all proxy + unit test | medium |
| `feat/cliproxy-upgrade` (partial) | RUNBOOK registry-backed `sync-models` docs and `--legacy` rollback path | low |
| `feat/final-consolidation-integration` | Removed `tests/integration/test_db_schema.py` — requires live Postgres host `postgres`, incompatible with in-memory mock CI | low |

## Already merged (worktrees safe to retire)

These branches have no meaningful unique commits vs `main`. Worktrees can be removed after this branch lands.

| Branch / worktree | Status |
|-------------------|--------|
| `feat/admin-ui-scaffold` | Scalar docs-server scaffold already on `main` |
| `feat/onboarding-reimplement` | Merged via PR #296 |
| `feat/policy-docs-update` | Merged via PR #295 |
| `feat/final-consolidation-integration` | Superseded by PR #294; only stale `.env.op` / doc reversions remain |
| `feat/issue-277` | Fault injection tests merged via PR #283 |
| `hotfix/auto-approve` | Merged via PR #291 |
| `feat/cliproxy-upgrade` | CPA pin + CLIProxy upgrade section already on `main` (now at v7.1.50) |
| `origin/feat/admin-trace-stacked` | Policy trace history endpoint exists on `main` (`GET /admin/status/policy`) |
| `origin/chore/remove-litellm-reloader` | Reloader removed via PR #290 |
| `origin/feat/virtual-provider` | Merged via PR #292 |
| `origin/feature/gateway-engine-rename` | Merged via PR #287 |
| `origin/feat/docker-naming-standardization` | Merged via PR #285 |
| `origin/feat/scaffold-in-memory-fixtures` | Merged via PR #279 |
| `origin/feat/issue-274`–`276`, `278` | Test ports merged via PRs #280–283 |
| `origin/feat/epic2-decommission-local` | Policy decommission merged via PR #290 |
| `origin/feat/credential-probe-shared-241` | Credential inventory admin API on `main` |

## Deferred — implement later

### Medium priority

| Feature | Branch | Why deferred | Suggested approach |
|---------|--------|--------------|-------------------|
| Unified config admin API | `feat/unified-config` | Built against `services/translator/` (renamed to `gateway-engine`); 25 commits behind | Re-implement as gateway-engine admin routes; compare with existing `admin_api.py` proxy |
| External model metadata expansion | `origin/feature/external-model-metadata` | Large `config/model-registry.yaml` expansion (~270 lines); may conflict with live cliproxy sync | Incremental model additions via registry sync + policy_metadata fields |
| OpenAPI server blocks for Scalar UI | `feat/admin-ui-scaffold` worktree (uncommitted `add_servers.py`) | Ad-hoc script, not reviewed; OpenAPI files modified locally only | Add `servers:` entries manually per spec with correct ports |
| Tenancy propagation E2E test | `origin/feat/final-fix` | `test_tenancy_propagation.py` depends on metadata paths not fully wired | Finish Epic #30 tenancy wiring first |
| Self-service onboarding extensions | `origin/feat/final-fix` | `/admin/tenants` panel, connectivity probe, key provisioning — partial overlap with #296 | Design review against `docs/maestro/plans/self-service-onboarding-plan.md` |

### Low priority / docs only

| Feature | Branch | Why deferred |
|---------|--------|--------------|
| Sanitized RUNBOOK SSH example | `feat/cliproxy-upgrade` | Cosmetic; main already uses example hostnames in most places |
| CI upgrade-stack-2026 | `origin/feat/upgrade-stack-2026` | 241 commits behind; Node 24 + venv CI changes need fresh rebase |
| Epic4-6 testing CI gates | `origin/feat/epic4-6-testing-ci-gates` | Gate C venv pytest fix; evaluate when real-provider E2E re-enabled |

### High risk — do not cherry-pick

| Feature | Branch | Why skip |
|---------|--------|----------|
| Full `feat/final-fix` stack | `origin/feat/final-fix` | 19 commits, reintroduces `litellm-reloader`, deletes onboarding/tests, 137-file diff |
| `feat/cliproxy-model-sync-232` | local worktree | Superseded by gateway-engine `/admin/models/sync` + probe APIs on `main` |
| `fix/mock-integration-failfast` | branch | Targets old Docker-based mock CI; `mock-integration` job now runs in-memory ASGI tests |
| `origin/feat/admin-policy-trace` | remote | 196 commits behind; reverts gateway-engine rename |
| `origin/feat/epic2-policy-evaluator` | remote | Superseded by in-process evaluator on `main` |
| `origin/chore/infrastructure-modernization` | remote | Overlaps merged PR #289; stale base |

## Stale worktree cleanup

After merging `chore/consolidate-unmerged-work`, consider removing:

```bash
git worktree remove /home/dev/worktrees/ai-gateway-admin-ui-scaffold
git worktree remove /home/dev/worktrees/ai-gateway-cliproxy-model-sync-232
git worktree remove /home/dev/worktrees/ai-gateway-cliproxy-upgrade
git worktree remove /home/dev/worktrees/ai-gateway-fix-dev-env-list
git worktree remove /home/dev/worktrees/ai-gateway-unified-config
git branch -d feat/admin-ui-scaffold feat/cliproxy-model-sync-232 feat/cliproxy-upgrade \
  fix/dev-env-list-cmd feat/unified-config
```

Uncommitted files in `ai-gateway-admin-ui-scaffold` (`add_servers.py`, `clean_openapi.py`, modified OpenAPI YAMLs) were **not** merged — capture requirements in the OpenAPI servers task above if still needed.

## Remote branches to close

These have zero unique value vs `main` and can be deleted on GitHub after verification:

- `feat/cliproxy-model-sync-232`, `feat/cliproxy-upgrade`, `feat/unified-config`
- `fix/dev-env-list-cmd`, `fix/mock-integration-failfast`
- `feat/onboarding-reimplement`, `feat/policy-docs-update`, `feat/issue-277`
- `feat/final-consolidation-integration`, `hotfix/auto-approve`
