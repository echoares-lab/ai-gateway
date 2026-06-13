# Unmerged Features Backlog

## Follow-up audit - 2026-06-13

Compared local worktrees, local branches, and remote branches against `origin/main` (`26b32b4`). No open PRs were present. Baseline `make test-unit` passed with `229 passed`; `./dev-env.sh start 1` returned a failure while LiteLLM was still recovering Prisma migrations, but the LiteLLM container became healthy shortly afterward. That startup behavior should be treated as a dev-stack wait/health issue, not as a permanent service failure.

### Applied in `feat/unmerged-work-recovery`

| Source | Change | Risk |
|--------|--------|------|
| `feat/admin-ui-scaffold` worktree (partial local edits) | Added current top-level OpenAPI `servers:` entries for `gateway-engine.yaml` and `litellm.yaml` so Scalar has usable local targets without importing stale `translator.yaml` deletions | low |

### Newly observed deferred work

| Feature | Source | Why deferred | Suggested approach |
|---------|--------|--------------|-------------------|
| Dev stack list/slot isolation cleanup | Current `dev-env.sh` plus `docker-compose.dev.yml` | `./dev-env.sh list` filters `aidev` names, but dev containers are fixed `TESTING-*` names; a full fix likely touches container naming, CI naming tests, and multi-slot semantics | Design a small infra change that either makes dev container names slot-aware or updates slot commands around the `TESTING-*` convention; include `tests/verify-docker-naming.sh` coverage |
| Dev stack wait timeout after long LiteLLM migration recovery | Current `./dev-env.sh start 1` run | Compose returned failure before LiteLLM became healthy; logs showed migration recovery completed and health probes returned 200 afterward | Add an explicit post-`up` condition wait with a longer LiteLLM budget, or document the first-start recovery path; verify with a clean dev volume |
| Self-hosted CI runner bootstrap script | `/home/dev/.cursor/worktrees/ai-gateway__SSH__dev_/wfd0/scripts/ci-runner-bootstrap.sh` | Local-only untracked script grants sudoers access and seeds system-level caches; useful but needs security review and docs alignment before import | Rework as a reviewed ops script linked from `docs/CI_SELF_HOSTED.md`; require shellcheck and a dry-run mode before merge |
| OpenAPI `servers:` for policy-engine spec | `feat/admin-ui-scaffold` worktree | The standalone policy engine has been decommissioned; adding a live localhost server target could mislead users | Either mark `docs/openapi/policy-engine.yaml` as historical/internal or document the gateway-engine admin route that exposes policy state |

### Reconfirmed high-risk skips

| Feature | Source | Reason |
|---------|--------|--------|
| CLIProxy model sync branch | `feat/cliproxy-model-sync-232` | Still targets `services/translator/**`; current main has gateway-engine registry/probe APIs and renamed OpenAPI docs |
| Full final-fix stack | `origin/feat/final-fix` | Large stale stack touching rename, tenancy, onboarding, CI, Docker, and deleted services; cherry-picking would be higher risk than reimplementation |
| Admin OpenAPI helper scripts | `feat/admin-ui-scaffold` worktree `add_servers.py`, `clean_openapi.py` | Ad-hoc scripts use regex and the local diff deletes hundreds of current gateway-engine endpoint docs from old `translator.yaml` |

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
