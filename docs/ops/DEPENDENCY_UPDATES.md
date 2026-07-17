# Per-Component Dependency Update Playbook

**Epic:** [#413](https://github.com/echoares-lab/ai-gateway/issues/413) — CLIProxy upstream patch and dependency update loop  
**Issue:** [#417](https://github.com/echoares-lab/ai-gateway/issues/417)  
**Inventory:** [`docs/DEPENDENCY_INVENTORY.md`](../DEPENDENCY_INVENTORY.md)  
**Design:** [`docs/superpowers/specs/2026-07-17-cliproxy-upstream-patch-dep-updates-design.md`](../superpowers/specs/2026-07-17-cliproxy-upstream-patch-dep-updates-design.md)  
**Automation:** [`.github/renovate.json`](../../.github/renovate.json)  
**Promote gate:** [`docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md`](../superpowers/specs/2026-07-17-staging-deep-smoke-design.md)

This document is the operator playbook for updating every third-party runtime image
inventoried in [`DEPENDENCY_INVENTORY.md`](../DEPENDENCY_INVENTORY.md). First-party images
(`gateway-engine`, `docs-server`, `credential-prober`) follow CI → Nexus →
[`promote-k3s-images.yml`](../../.github/workflows/promote-k3s-images.yml); they are out of
scope here.

Use this playbook together with the inventory summary table. Every update PR must record
**old pin**, **new pin**, **release-note range**, **gates run**, **evidence links**, and
**rollback target**. Unknown migration reversibility **blocks** production promotion.

---

## Gate reference

| Gate | Command / trigger | Blocks merge to `main`? | Blocks k3s prod pin? |
|------|-------------------|-------------------------|----------------------|
| **A** | `make lint`, `make test-unit` | Yes | No (already on `main`) |
| **B** | `make test-mock` | Yes when runtime/wire paths change | No |
| **C** | `make test-e2e` or PR label `run-e2e` | No (opt-in / advisory) | No |
| **Deep smoke `--full`** | `./scripts/ops/deep-smoke.sh --env staging --full` | No | **Yes** — CI-enforced by `promote-k3s-images.yml` → `staging-deep-smoke.yml` (#410) |
| **D** | `./cliproxy-setup.sh health` + three model smokes (stable `:4000`) or prod k8s `--quick` | No (post-merge advisory) | No (post-promote verification) |

See [`docs/TESTING.md`](../TESTING.md) and
[`docs/process/TESTING_AND_PROMOTION_POLICY.md`](../process/TESTING_AND_PROMOTION_POLICY.md)
for full gate definitions.

**Deep smoke vs Gate D:** Deep smoke `--full` on staging is the **promote gate** before opening
a k3s-01 production digest-pin PR. Gate D is a **thin** post-merge / post-promote smoke on the
production edge. Do not substitute Gate D for staging `--full` on high-risk components.

---

## Standard promote path (k3s)

Third-party image bumps land in this repo first (compose pins + Renovate PRs). Production
consumes **immutable digests** from the external **k3s-01** GitOps repo.

```text
  [ Update intake ]     Renovate PR or CLIProxy weekly candidate (#11)
         │
         ▼
  [ Merge to main ]     Gates A (+ B when applicable); CI green
         │
         ▼
  [ Staging pin ]       k3s-01 overlay `ai-gateway-staging` — exact digest under test
         │              ArgoCD sync + workload readiness
         ▼
  [ Deep smoke ]        ./scripts/ops/deep-smoke.sh --env staging --full
         │              (or CI `staging-deep-smoke.yml` via promote workflow)
         ▼
  [ Prod pin PR ]       k3s-01 overlay `k3s-01` — same digest as staging evidence
         │              PR body: digest, staging revision, deep-smoke summary, prior digest
         ▼
  [ Gate D ]            Health + claude/gpt/gemini smokes; quota summary for cliproxy
```

Emergency bypass: `promote-k3s-images.yml` `workflow_dispatch` input
`skip_deep_smoke=true` skips the staging gate — operator-only, must be recorded in the PR/issue
thread.

Local compose / dev slots validate pins before merge but do **not** replace staging deep-smoke
for k3s promotion.

---

## Dependency update PR checklist

Copy into every Renovate PR body (Renovate template enforces most fields) and every manual
dependency PR:

```markdown
## Dependency update

| Field | Value |
|-------|-------|
| Component | <!-- e.g. LiteLLM --> |
| Old pin | <!-- tag + digest --> |
| New pin | <!-- tag + digest --> |
| Update source | <!-- Renovate / CLIProxy weekly / manual --> |
| Release notes | <!-- link + version range --> |
| Migration / config changes | <!-- Prisma, Langfuse, ClickHouse, etc. --> |
| Risk tier | <!-- high / medium / low-medium --> |

## Pre-merge gates (ai-gateway repo)

- [ ] Gate A: `make lint` + `make test-unit`
- [ ] Gate B: `make test-mock` (if wire format / routing may change)
- [ ] YAML / compose validation (see commands in component section)
- [ ] Gate C: `make test-e2e` or `run-e2e` label (recommended for auth/provider-facing bumps)

## Pre-promotion gates (k3s)

- [ ] Staging overlay pinned to **this exact digest**
- [ ] ArgoCD sync + pods Ready
- [ ] `./scripts/ops/deep-smoke.sh --env staging --full` green (paste summary)
- [ ] Component-specific checks (from section below)

## Rollback

| Target | Command / action |
|--------|------------------|
| Previous digest/tag | <!-- e.g. ghcr.io/.../litellm:v1.87.0@sha256:… --> |
| k3s prod revert | <!-- one-commit revert PR on k3s-01 overlay --> |
| Compose / dev | <!-- restore prior image: lines in docker-compose*.yml --> |
| Data restore | <!-- only if migration not backward-compatible; see component section --> |

Migration reversibility unknown → **do not promote to production**.
```

---

## Component playbooks

Each section follows the same shape: **update intake**, **pre-merge gates**, **staging promote**,
**production verification**, **rollback**, and **compatibility notes**.

Pin locations and current values: [`DEPENDENCY_INVENTORY.md`](../DEPENDENCY_INVENTORY.md).

---

### CLIProxy / cliproxy

| | |
|---|---|
| **Risk** | High |
| **Update source** | CLIProxyAPI weekly upstream-track job (#11) → Nexus immutable candidate digest — **not Renovate** |
| **Pin locations** | `docker-compose.yml`, `docker-compose.dev.yml`, `.env.example` (`CLIPROXY_IMAGE`), k3s-01 staging/prod overlays |

#### How updates arrive

1. CLIProxyAPI #11 rebases the two-commit quota stack on upstream, runs fork + quota tests, builds
   an image, and publishes to Nexus with provenance (upstream SHA + patch-head SHA).
2. The job opens an actionable PR or issue with digest, test results, release notes, and rollback
   digest.
3. ai-gateway promotion uses [`promote-k3s-images.yml`](../../.github/workflows/promote-k3s-images.yml)
   (#415) or a manual k3s-01 staging pin for the candidate digest.

Failed rebase, failed quota contract, missing provenance, or failed image scan **stops**
candidate publication. Patch count greater than two is drift — requires design update (#414).

#### Pre-merge gates (ai-gateway repo)

Cliproxy digest changes in compose typically arrive via a dedicated cutover PR (#418), not
Renovate:

- Gate A: `make lint`, `make test-unit`
- Gate B: `make test-mock`
- Gate C: **recommended** — `make test-e2e` or `run-e2e` (auth / provider-facing)
- CLIProxyAPI fork tests + ai-gateway quota contract (CLIProxyAPI #13)
- Image scan on the Nexus candidate
- Auth PVC compatibility review (token file format unchanged, or migration documented)

#### Staging promote

1. Resolve Nexus candidate tag → immutable digest.
2. Pin digest in k3s-01 `ai-gateway-staging` overlay.
3. Wait for ArgoCD sync; confirm cliproxy pod image ID matches digest.
4. Run staging deep-smoke:

   ```bash
   ./scripts/ops/deep-smoke.sh --env staging --full
   ```

   Quota assertions (`GET /admin/quota/status`) are **hard failures** (#403 OpenAPI contract).
5. Confirm OAuth PVC remains usable (credentials list non-error in deep-smoke admin checks).

#### Production verification (Gate D)

After prod Argo sync:

```bash
./cliproxy-setup.sh health
./cliproxy-setup.sh test claude-sonnet-4-6   # or current claude allowlist model
./cliproxy-setup.sh test gpt-5-4
./cliproxy-setup.sh test gemini-3-flash
./cliproxy-setup.sh quota-summary
```

Verify pod image ID matches the staging-tested digest. Record evidence in the promote PR and
epic closeout.

#### Rollback

| Scenario | Action |
|----------|--------|
| **Image rollback** | Revert k3s-01 prod overlay to prior Nexus digest (one-commit revert PR). Update compose `CLIPROXY_IMAGE` only after prod is stable. |
| **OAuth token format unchanged** | Prior digest is sufficient; do **not** reseed prod PVC from staging. |
| **Token format changed** | Restore OpenBao archive `cliproxy_auth_tar_b64` into prod PVC per [`docs/ops/RUNBOOK.md`](RUNBOOK.md); never copy staging credentials into production. |

#### Rollback drill (required before epic #413 closeout)

On staging only:

1. Record candidate digest **N**, previous **N−1**, Argo revision, auth archive reference.
2. Promote **N** → pass `--full`.
3. Revert staging to **N−1** → pass `--full` again.
4. Restore **N** → pass `--full`.
5. Attach timestamps and summaries to epic #413.

Drill fails if any digest is mutable, credentials need undocumented manual repair, or **N−1**
cannot restore a green deep-smoke.

---

### LiteLLM

| | |
|---|---|
| **Risk** | High |
| **Update source** | Renovate (`ghcr.io/berriai/litellm`) — separate PR per update; digest pin required; no auto-merge |
| **Pin locations** | `docker-compose.yml`, `docker-compose.dev.yml` (litellm ×2, litellm-migrate), `scripts/ops/generate-litellm-mock-seed.sh` |

#### How updates arrive

Renovate opens a PR updating the image tag/digest in compose files. Review upstream
[LiteLLM releases](https://github.com/BerriAI/litellm/releases) for Prisma schema changes,
provider behavior, and breaking API shifts.

Obtain digest after choosing tag:

```bash
docker pull ghcr.io/berriai/litellm:vX.Y.Z
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/berriai/litellm:vX.Y.Z
```

Update all pin locations to `image:tag@sha256:…` in one PR.

#### Pre-merge gates

- Gate A: `make lint`, `make test-unit`
- Gate B: `make test-mock` (**required** — wire format / routing)
- Config validation:

  ```bash
  python3 -c "import yaml; yaml.safe_load(open('litellm-config.yaml'))"
  pytest tests/test_litellm_compose_migration.py -v
  ```

- **Prisma migration review:** read release notes; inspect `litellm-migrate` job / Prisma
  migrations in the new image. If migrations are not backward-compatible, plan DB backup before
  promote.
- Gate C: **recommended** for provider/auth/config changes — `make test-e2e` or `run-e2e`
- Local slot smoke (optional, pre-PR):

  ```bash
  ./dev-env.sh rebuild 1   # after compose pin change
  docker exec aidev1-litellm-1 prisma migrate deploy  # if migrate job not used locally
  ./cliproxy-setup.sh health
  ./cliproxy-setup.sh test claude-sonnet-4-6
  ```

#### Staging promote

1. Merge Renovate PR to `main`.
2. Pin **same digest** in k3s-01 staging overlay (litellm Deployment + litellm-migrate Job image).
3. Argo sync; confirm `litellm-migrate` Job succeeded (not `Failed`).
4. `./scripts/ops/deep-smoke.sh --env staging --full` — SpendLogs side-effect check validates DB
   path through LiteLLM.

#### Production verification (Gate D)

After prod pin + sync: health, `/v1/models`, provider-family smokes, spend log ingestion. Deep
smoke `--quick` on prod is optional for incidents.

#### Rollback

| Scenario | Action |
|----------|--------|
| **Backward-compatible migration** | Revert image digest in k3s-01 prod overlay + compose. |
| **Non-reversible migration** | Restore `litellm` DB from pre-update backup into prior major/minor **before** or **instead of** image-only revert. Prefer backup **before** promote when release notes mention schema changes. |
| **Dev slot** | Revert `docker-compose.dev.yml` pins; `./dev-env.sh stop 1 && ./dev-env.sh start 1`. |

**Rule:** revert image first when migrations allow; restore DB only when image rollback is
insufficient.

---

### CPA-Manager

| | |
|---|---|
| **Risk** | Medium |
| **Update source** | Renovate (`seakee/cpa-manager`) — patch/minor grouping; no auto-merge |
| **Pin locations** | `docker-compose.yml`, `docker-compose.dev.yml` |

#### How updates arrive

Renovate PR updates the image tag. Review
[cpa-manager releases](https://github.com/seakee/cpa-manager/releases) for SQLite schema or
management API changes.

#### Pre-merge gates

- Gate A: `make lint`, `make test-unit`
- Compose validation:

  ```bash
  python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"
  python3 -c "import yaml; yaml.safe_load(open('docker-compose.dev.yml'))"
  ```

- Local startup + management UI/API smoke:

  ```bash
  docker compose up -d cpa-manager
  curl -sf http://localhost:18317/management.html >/dev/null
  ```

Gate B/C generally not required unless gateway integration paths change.

#### Staging promote

1. Pin digest in k3s-01 staging overlay.
2. Argo sync; pod Ready.
3. Deep smoke `--full` (admin + request path); confirm usage ingestion still current in CPA UI.

#### Production verification

Management UI reachable; usage analytics ingestion current.

#### Rollback

Revert to prior tag/digest in k3s-01 prod overlay + compose. **Preserve** the CPA SQLite PVC —
do not delete the volume on rollback.

---

### Langfuse (web + worker)

| | |
|---|---|
| **Risk** | Medium |
| **Update source** | Renovate — **web and worker grouped**; must stay on the **same version** |
| **Pin locations** | `docker-compose.yml` (`langfuse/langfuse:3`, `langfuse/langfuse-worker:3`) |

#### How updates arrive

Renovate grouped PR bumps both images. Treat floating `:3` as discovery until digest-pinned
(see inventory floating-pins table).

#### Pre-merge gates

- Gate A + compose YAML validation
- **Migration review:** Langfuse release notes for Postgres/ClickHouse schema changes
- Local or staging: trace ingestion + worker health (Langfuse UI shows new traces; worker logs
  clean)

Gate B optional unless gateway trace headers change.

#### Staging promote

Pin **both** web and worker to the same digest in k3s-01 staging. Run deep smoke `--full`;
Langfuse trace check is warn-only unless `--strict`.

#### Production verification

New trace searchable in Langfuse UI; workers healthy (`kubectl -n ai-gateway logs` worker
Deployment).

#### Rollback

Revert **both** Langfuse images together to the prior paired digests. Database restore only when
documented migration incompatibility — coordinate with ClickHouse/MinIO sections if object store
or analytics schema changed.

---

### ClickHouse

| | |
|---|---|
| **Risk** | Medium |
| **Update source** | Renovate (`clickhouse/clickhouse-server`) — majors in **separate PR**; digest pin encouraged |
| **Pin locations** | `docker-compose.yml` (currently floating tag — pin via Renovate) |

#### How updates arrive

Renovate proposes digest-pinned updates. Major bumps require isolated PR and explicit migration
review.

#### Pre-merge gates

- Compose / config validation
- **Backup** ClickHouse data volume before staging experiment
- Langfuse read/write smoke after bump (trace queries still work)

#### Staging promote

Pin digest in k3s-01 staging StatefulSet. Deep smoke `--full` (Langfuse path). Storage health:
`kubectl -n ai-gateway-staging get pvc`.

#### Production verification

Langfuse ingestion and retrieval against ClickHouse backend.

#### Rollback

Restore prior image digest **and** compatible data snapshot if schema migration ran. Without
snapshot, major rollback may be impossible — backup before major promote.

---

### MinIO

| | |
|---|---|
| **Risk** | Medium |
| **Update source** | Renovate (`cgr.dev/chainguard/minio`) — majors separated; digest pin encouraged |
| **Pin locations** | `docker-compose.yml` (floating tag today) |

#### How updates arrive

Same pattern as ClickHouse — Renovate digest PRs; majors isolated.

#### Pre-merge gates

- Compose validation
- **Backup** bucket / volume before staging bump
- Object read/write smoke (Langfuse media / event uploads)

#### Staging promote

Pin digest in k3s-01 staging MinIO StatefulSet. Deep smoke `--full`.

#### Production verification

Langfuse object retrieval; MinIO health endpoints.

#### Rollback

Prior image + bucket snapshot when data format changed. Volume-preserving tag revert when
compatible.

---

### Redis

| | |
|---|---|
| **Risk** | Low–medium |
| **Update source** | Renovate (`redis:7`) — patch/minor grouping within v7 |
| **Pin locations** | `docker-compose.yml`, `docker-compose.dev.yml` |

#### How updates arrive

Renovate PR for patch/minor updates on the `7` major line.

#### Pre-merge gates

- Gate A: `make lint`, `make test-unit`
- Gate B: `make test-mock` when cache serialization paths may change
- Cache health (when `CACHE_ENABLED=true` in test env):

  ```bash
  source .env && curl -s http://localhost:4000/cache/ping \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY"
  ```

Production default: LiteLLM auth-aware cache preferred; gateway-engine `CACHE_ENABLED=false`.

#### Staging promote

Pin digest in overlay if Redis is app-scoped; staging uses shared platform Redis
(`redis.database.svc`) — coordinate with platform team for shared instance bumps.

Deep smoke `--full` optional for patch bumps; required when cache behavior affects gateway.

#### Production verification

Redis connectivity; representative cached request behavior if caching enabled.

#### Rollback

Revert minor/digest. **Flush cache** only when serialization format changed (rare on patch
bumps).

---

### Postgres (compose / dev stacks)

| | |
|---|---|
| **Risk** | Low–medium |
| **Update source** | Renovate (`postgres:17`) — **automatic major disabled**; manual issue for major |
| **Pin locations** | `docker-compose.yml`, `docker-compose.dev.yml`, `${POSTGRES_VERSION:-17}` |

#### How updates arrive

Renovate patch/minor within PostgreSQL 17. Major version bumps require a manual issue, backup
drill, and Renovate rule override.

#### Pre-merge gates

- Gate A + compose validation
- **Major:** backup/restore proof on dev slot before merge
- Integration tests touching DB migrations:

  ```bash
  pytest tests/test_litellm_compose_migration.py -v
  ```

- Service integration: `./dev-env.sh test 1` when migrate jobs change

#### Staging promote

Staging uses shared CNPG (`litellm_staging`, `langfuse_staging` on `platform-postgres`) — see
Postgres (k3s) below. Compose-only bumps validate on dev slots; k3s DB engine is platform-owned.

#### Production verification

DB readiness; migration Jobs succeeded; spend logging works (deep smoke SpendLogs check).

#### Rollback

| Scenario | Action |
|----------|--------|
| **On-disk format compatible** | Revert `postgres:17.x` image tag in compose. |
| **Major upgrade attempted** | Restore volume from backup into **prior major** image — do not downgrade data directory in place blindly. |

---

### Postgres (k3s — CNPG platform cluster)

| | |
|---|---|
| **Risk** | Medium |
| **Update source** | Platform team / CNPG operator — **not** Renovate in this repo |
| **Pin locations** | k3s-01 `database` namespace — `platform-postgres` cluster |

#### How updates arrive

Coordinated platform upgrade of the CNPG cluster image. ai-gateway consumes
`platform-postgres-rw.database.svc:5432` for `litellm`, `langfuse`, and staging counterparts.

#### Pre-merge gates (ai-gateway repo)

No compose pin change. Track platform change request:

- Confirm `litellm-migrate` and `gateway-migrate` Jobs still succeed on staging
- Run deep smoke `--full` after platform rolling upgrade on staging
- Review PostgreSQL extension compatibility (LiteLLM Prisma, Langfuse)

#### Staging promote

Platform team runs CNPG rolling upgrade on staging cluster or maintenance window. ai-gateway
validates via deep smoke + migration Job status.

#### Production verification

CNPG cluster healthy; ai-gateway migration Jobs Completed; Gate D spend/model smokes.

#### Rollback

CNPG rollback / PITR per **platform runbook** — not governed by ai-gateway compose revert alone.
Open ai-gateway incident if migrations fail after platform rollback.

---

## Quick reference matrix

Derived from epic #413 design spec and [`DEPENDENCY_INVENTORY.md`](../DEPENDENCY_INVENTORY.md).

| Component | Pre-merge | Staging promote gate | Prod verification | Rollback target |
|-----------|-----------|----------------------|-------------------|-----------------|
| cliproxy | A, B, C†, fork/quota tests, scan | `--full` + quota + PVC | Image ID, health, 3 smokes, quota | Prior Nexus digest; OpenBao auth archive if format changed |
| LiteLLM | A, B, config, migration review, C† | `--full` + migrate Job | Models, smokes, spend log | Prior digest; DB backup if migration irreversible |
| CPA-Manager | A, compose, UI smoke | `--full` | UI + ingestion | Prior digest; keep SQLite PVC |
| Langfuse web/worker | A, migration review | `--full` (trace warn) | Traces + workers | Revert **both** images; DB if needed |
| ClickHouse | backup, config | `--full` | Langfuse R/W | Prior image + snapshot |
| MinIO | backup, object smoke | `--full` | Langfuse objects | Prior image + bucket snapshot |
| Redis | A, B‡, cache health | platform or `--full` if behavior change | connectivity | Prior digest; flush if serialization changed |
| Postgres compose | A, backup‡‡, integration | dev slot / N/A shared | migrate Jobs, spend log | Prior tag or backup restore |
| Postgres CNPG | platform coordination | `--full` after platform upgrade | cluster + Jobs | Platform PITR |

† Gate C recommended for auth/provider-facing changes.  
‡ Gate B when cache paths may change.  
‡‡ Backup/restore proof required for major.

---

## Related documents

| Document | Role |
|----------|------|
| [`docs/DEPENDENCY_INVENTORY.md`](../DEPENDENCY_INVENTORY.md) | Pin locations, risk tiers, Renovate policy |
| [`docs/ops/RUNBOOK.md`](RUNBOOK.md) | Day-to-day operations, OAuth, legacy upgrade notes |
| [`docs/CICD_PHASE2_STAGING.md`](../CICD_PHASE2_STAGING.md) | Staging namespace, databases, promotion |
| [`docs/CICD_PHASE2_CD_K3S.md`](../CICD_PHASE2_CD_K3S.md) | Production k3s mapping |
| [`docs/TESTING.md`](../TESTING.md) | Gate commands and CI parity |
| [`scripts/ops/deep-smoke.sh`](../../scripts/ops/deep-smoke.sh) | Staging promote gate entrypoint |
