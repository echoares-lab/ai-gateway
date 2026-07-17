# Staging Deep Smoke (Promote Gate) — Design

**Date:** 2026-07-17  
**Status:** Approved for implementation via GitHub epic + atomic children  
**Primary target:** Staging k8s (`ai-gateway-staging`)  
**Role:** Human/process **promote gate** before pinning digests to production

## Goal

Provide an on-demand operator deep-smoke that covers production-path gaps CI and thin post-merge Gate D do not hit: multi-API shapes, streaming, admin surfaces, cluster readiness, and database side effects (`LiteLLM_SpendLogs`). Staging `--full` must pass before a k3s-01 production digest-pin PR is opened/merged.

## Non-goals

- Replace advisory `post-merge-gate-d.yml` (thin prod edge smoke after merge remains).
- Block every merge to `main`.
- Require Langfuse credentials (best-effort / warn-only).
- Harden assertions against a frozen `GET /admin/quota/status` schema while quota work is in flux (soft check only).

## Placement in the promotion flow

1. Candidate images/config land on staging (`:latest` / staging overlay).
2. Operator runs `./scripts/ops/deep-smoke.sh --env staging --full`.
3. On green: open/merge the k3s-01 GitOps PR that pins the **exact** validated digests/config to prod.
4. After prod sync: thin Gate D (existing workflow / manual) is sufficient; optional `--env prod --quick` for incidents.

## CLI

```bash
./scripts/ops/deep-smoke.sh --env staging|prod [--quick|--full] [--strict] [--allow-mutating-admin]
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--env staging` | yes (promote path) | Namespace `ai-gateway-staging`, staging ingress URL |
| `--env prod` | optional | Namespace `ai-gateway`; incident / optional post-promote |
| `--full` | default when staging | Promote-gate depth |
| `--quick` | incident path | Health, version, models, one completion, pods Ready |
| `--strict` | off | Promote warnings (e.g. missing Langfuse) to failures |
| `--allow-mutating-admin` | off | Opt-in for admin probe/sync; never model delete / credential wipe |

Exit non-zero on any hard failure. Print a pasteable markdown summary (GitOps PR / closeout).

## Check inventory

### `--quick`

1. `GET /health` → 200  
2. `GET /health/ready` → 200 (or documented ready semantics)  
3. `GET /version` → JSON with `version` / `git_sha` / `display_version`  
4. `GET /v1/models` → `data.length > 0`  
5. One cheap `POST /v1/chat/completions` (`max_tokens` tiny, tagged end_user)  
6. `kubectl -n <ns> get pods` — all workloads Ready (or explicit allowlist)

### `--full` (includes `--quick`)

7. **API shapes** — tagged requests: `/v1/chat/completions`, `/v1/responses`, `/v1/messages`  
8. **Streaming** — one SSE chat stream; ≥1 `data:` chunk; clean finish  
9. **Provider families** — cheap completion for claude / gpt / gemini allowlist  
10. **Admin (read-mostly)** — `/admin/status` 2xx; credentials list non-error  
11. **Quota (soft)** — `GET /admin/quota/status` → 2xx + parseable JSON object only. **Do not assert field contracts** until quota schema is explicitly frozen in OpenAPI / the quota design. Document soft contract in script comments and TESTING docs.  
12. **Cluster** — pods Ready; bootstrap/migration Jobs not `Failed` when present  
13. **DB side effect** — after a tagged completion, poll `LiteLLM_SpendLogs` via kubectl/psql for a recent row matching smoke `end_user` (or `request_id`) within a short window  
14. **Langfuse** — if creds set, confirm a recent trace; else warn (fail only with `--strict`)

## Auth & config (never commit secrets)

| Variable | Purpose |
|----------|---------|
| `DEEP_SMOKE_GATEWAY_URL` | Override default staging/prod ingress |
| `DEEP_SMOKE_API_KEY` | Dedicated smoke virtual key (preferred) |
| `DEEP_SMOKE_ADMIN_KEY` | Optional `x-admin-key` |
| `DEEP_SMOKE_K8S_NAMESPACE` | Override namespace |
| `DEEP_SMOKE_KUBE_CONTEXT` | Optional kubectl context |
| `DEEP_SMOKE_PG_*` / kubectl exec into postgres | SpendLogs query path |
| `DEEP_SMOKE_LANGFUSE_*` | Optional; warn-only if unset |
| `DEEP_SMOKE_MODELS` | Optional override of provider-family model ids |

Defaults:

- staging URL: `https://gateway-staging.infra.plexplease.com`
- prod URL: `https://gateway.infra.plexplease.com` (or public edge if that is the operator canonical)

## Safety

- Tag all smoke traffic (`end_user=deep-smoke-<utc-ts>`, tiny prompts/`max_tokens`).
- Default `--env staging` to reduce accidental prod quota burn.
- No destructive admin mutations without `--allow-mutating-admin`.
- `--full` on staging **requires** kubectl (and DB access path); fail clearly if missing.

## Relationship to existing gates

| Gate | Role |
|------|------|
| A/B | Pre-merge CI |
| C | Opt-in real-provider E2E |
| D (`post-merge-gate-d`) | Thin advisory prod edge after `main` push |
| **Deep smoke `--full` (this)** | **Staging promote gate** before prod digest pin |

## Artifacts

| Path | Role |
|------|------|
| `scripts/ops/deep-smoke.sh` | Operator entrypoint |
| `scripts/ops/deep_smoke.py` | JSON/DB assertion helper (preferred over fragile pure bash) |
| `tests/test_deep_smoke_*.py` or `tests/test-deep-smoke.sh` | Offline unit/shell tests with fakes |
| `.env.example` | Document `DEEP_SMOKE_*` vars (no secrets) |
| `docs/CICD_PHASE2_STAGING.md` | Promote checklist step |
| `docs/CICD_PHASE2_CD_K3S.md` | Note: deep smoke is staging-side; prod Gate D stays thin |
| `docs/TESTING.md` / appendix | Gate D vs deep-smoke distinction |
| `docs/API_DOCUMENTATION.md` / OpenAPI | Cross-link soft quota smoke contract while schema moves |

## Blockers / soft dependencies

| Item | Impact | Mitigation |
|------|--------|------------|
| Quota endpoint schema still changing | Cannot freeze field asserts | Soft 2xx+JSON only; follow-up issue to harden after OpenAPI freeze |
| Staging smoke virtual key + admin key | Cannot run live `--full` | Ops provision; script fails with clear message |
| kubectl context + postgres access for SpendLogs | DB check fails | Required for staging promote path; document setup |
| Staging cluster unhealthy / not synced | Promote gate red | Expected — do not promote |
| Live staging run not available in Cursor Cloud | Cannot Gate-C the smoke itself in cloud VM | Offline tests in CI; live run on operator machine / ARC with kube |

## Success criteria

- Staging `--full` is the documented promote gate in CICD staging docs.
- Offline tests cover argument parsing, soft quota behavior, SpendLogs match helper, and failure exit codes.
- Operator can paste markdown summary into GitOps PR / issue closeout.
- Thin Gate D remains unchanged unless a later issue explicitly expands it.
