# Unmerged Features Backlog

## Follow-up audit - 2026-06-13

Compared local worktrees, local branches, and remote branches against `origin/main` (`26b32b4`). No open PRs were present. Baseline `make test-unit` passed with `229 passed`; `./dev-env.sh start 1` returned a failure while LiteLLM was still recovering Prisma migrations, but the LiteLLM container became healthy shortly afterward. That startup behavior should be treated as a dev-stack wait/health issue, not as a permanent service failure.

### Applied in `feat/unmerged-work-recovery`

| Source | Change | Risk |
|--------|--------|------|
| Local OpenAPI audit | Added current top-level OpenAPI `servers:` entries for `gateway-engine.yaml` and `litellm.yaml` so Scalar has usable local targets without importing stale `translator.yaml` deletions | low |

### Newly observed deferred work

| Feature | Source | Why deferred | Suggested approach |
|---------|--------|--------------|-------------------|
| Dev stack list/slot isolation cleanup | Current `dev-env.sh` plus `docker-compose.dev.yml` | `./dev-env.sh list` filters `aidev` names, but dev containers are fixed `TESTING-*` names; a full fix likely touches container naming, CI naming tests, and multi-slot semantics | Design a small infra change that either makes dev container names slot-aware or updates slot commands around the `TESTING-*` convention; include `tests/verify-docker-naming.sh` coverage |
| Dev stack wait timeout after long LiteLLM migration recovery | Current `./dev-env.sh start 1` run | Compose returned failure before LiteLLM became healthy; logs showed migration recovery completed and health probes returned 200 afterward | Add an explicit post-`up` condition wait with a longer LiteLLM budget, or document the first-start recovery path; verify with a clean dev volume |
| Self-hosted CI runner bootstrap script | `/home/dev/.cursor/worktrees/ai-gateway__SSH__dev_/wfd0/scripts/ci-runner-bootstrap.sh` | Local-only untracked script grants sudoers access and seeds system-level caches; useful but needs security review and docs alignment before import | Rework as a reviewed ops script linked from `docs/CI_SELF_HOSTED.md`; require shellcheck and a dry-run mode before merge |
| OpenAPI `servers:` for policy-engine spec | Current policy-engine OpenAPI spec | The standalone policy engine has been decommissioned; adding a live localhost server target could mislead users | Either mark `docs/openapi/policy-engine.yaml` as historical/internal or document the gateway-engine admin route that exposes policy state |

Audit date: 2026-06-09. Evaluated all local worktrees and remote branches against `main` (`001c5d9`).
Risk tiers: **low** (docs/small fix), **medium** (isolated feature), **high** (large refactor / stale base).

## Applied in `chore/consolidate-unmerged-work`

| Source | Change | Risk |
|--------|--------|------|
| `fix/dev-env-list-cmd` | Removed duplicate `cmd_list()` definition in `dev-env.sh` (function was defined twice) | low |
| `feat/cliproxy-upgrade` (partial) | RUNBOOK registry-backed `sync-models` docs and `--legacy` rollback path | low |
| `feat/final-consolidation-integration` | Removed `tests/integration/test_db_schema.py` — requires live Postgres host `postgres`, incompatible with in-memory mock CI | low |

## Deferred — implement later

### Medium priority

| Feature | Branch | Why deferred | Suggested approach |
|---------|--------|--------------|-------------------|
| Unified config admin API | `feat/unified-config` | Built against `services/translator/` (renamed to `gateway-engine`); 25 commits behind | Re-implement as gateway-engine admin routes; compare with existing `admin_api.py` proxy |
| External model metadata expansion | `origin/feature/external-model-metadata` | Large `config/model-registry.yaml` expansion (~270 lines); may conflict with live cliproxy sync | Incremental model additions via registry sync + policy_metadata fields |

### Low priority / docs only

| Feature | Branch | Why deferred |
|---------|--------|--------------|
| Sanitized RUNBOOK SSH example | `feat/cliproxy-upgrade` | Cosmetic; main already uses example hostnames in most places |
| CI upgrade-stack-2026 | `origin/feat/upgrade-stack-2026` | 241 commits behind; Node 24 + venv CI changes need fresh rebase |
| Epic4-6 testing CI gates | `origin/feat/epic4-6-testing-ci-gates` | Gate C venv pytest fix; evaluate when real-provider E2E re-enabled |

### High risk — do not cherry-pick

| Feature | Branch | Why skip |
|---------|--------|----------|
| `fix/mock-integration-failfast` | branch | Targets old Docker-based mock CI; `mock-integration` job now runs in-memory ASGI tests |
| `origin/feat/admin-policy-trace` | remote | 196 commits behind; reverts gateway-engine rename |
| `origin/feat/epic2-policy-evaluator` | remote | Superseded by in-process evaluator on `main` |
| `origin/chore/infrastructure-modernization` | remote | Overlaps merged PR #289; stale base |
