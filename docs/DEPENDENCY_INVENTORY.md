# Third-Party Runtime Dependency Inventory

**Epic:** [#413](https://github.com/echoares-lab/ai-gateway/issues/413) — CLIProxy upstream patch and dependency update loop  
**Issue:** [#416](https://github.com/echoares-lab/ai-gateway/issues/416)  
**Design:** [`docs/superpowers/specs/2026-07-17-cliproxy-upstream-patch-dep-updates-design.md`](superpowers/specs/2026-07-17-cliproxy-upstream-patch-dep-updates-design.md) (from #414)  
**Automation:** [`.github/renovate.json`](../.github/renovate.json)  
**Playbook:** [`docs/ops/DEPENDENCY_UPDATES.md`](ops/DEPENDENCY_UPDATES.md) (#417)

This document is the authoritative inventory of **third-party runtime images** consumed by
ai-gateway. First-party images (`gateway-engine`, `docs-server`, `credential-prober`) are built
from this repository and promoted through CI — they are out of scope here.

## Summary table

| Component | Current pin (2026-07-17) | Pin locations | Update source | Risk | Update mechanism | Pre-promotion gate | Rollback |
|-----------|--------------------------|---------------|---------------|------|------------------|--------------------|----------|
| **CLIProxy / cliproxy** | `nexus-docker.infra.plexplease.com/cli-proxy-api:c305d49` | `docker-compose.yml`, `docker-compose.dev.yml`, `.env.example` (`CLIPROXY_IMAGE`) | CLIProxyAPI weekly upstream-track job → Nexus candidate digest | **High** | **Not Renovate** — immutable candidate digest via #11 / #415 promote workflow | Fork tests; quota contract; image scan; staging `deep-smoke --full`; auth PVC compatibility | Prior Nexus digest; restore OpenBao `cliproxy_auth_tar_b64` only if token format changed |
| **LiteLLM** | `ghcr.io/berriai/litellm:v1.87.1@sha256:9de33287…cfd7b` | `docker-compose.yml`, `docker-compose.dev.yml` (×3 services), `scripts/ops/generate-litellm-mock-seed.sh` (`LITELLM_IMAGE` default) | Renovate (`ghcr.io/berriai/litellm`) | **High** | Renovate PR; digest pin required; no auto-merge | Gate A/B; config validation; staging `--full`; Prisma migration review; Gate C for provider/auth changes | Revert image; DB restore only when migration is not backward-compatible |
| **CPA-Manager** | `seakee/cpa-manager:1.5.5` | `docker-compose.yml`, `docker-compose.dev.yml` | Renovate (`seakee/cpa-manager`) | **Medium** | Renovate PR; patch/minor grouping; no auto-merge | Compose validation; startup; management UI/API smoke | Revert tag/digest; preserve SQLite volume |
| **Langfuse web** | `docker.io/langfuse/langfuse:3` | `docker-compose.yml` | Renovate (grouped with worker) | **Medium** | Renovate PR; **must stay on same version as worker** | Compose validation; migration review; trace ingestion + worker health on staging | Revert both Langfuse images together |
| **Langfuse worker** | `docker.io/langfuse/langfuse-worker:3` | `docker-compose.yml` | Renovate (grouped with web) | **Medium** | Renovate PR; grouped with web | Same as Langfuse web | Same as Langfuse web |
| **ClickHouse** | `docker.io/clickhouse/clickhouse-server` *(floating `latest`)* | `docker-compose.yml` | Renovate | **Medium** | Renovate PR; **majors in separate PR**; digest pin encouraged | Config validation; backup; storage health; Langfuse read/write smoke | Prior image + compatible data snapshot |
| **MinIO** | `cgr.dev/chainguard/minio` *(floating `latest`)* | `docker-compose.yml` | Renovate | **Medium** | Renovate PR; **majors in separate PR**; digest pin encouraged | Config validation; backup; object read/write smoke | Prior image + bucket snapshot |
| **Redis** | `docker.io/redis:7` | `docker-compose.yml`, `docker-compose.dev.yml` | Renovate | **Low–medium** | Renovate PR; patch/minor grouping | Config validation; unit/mock suite; cache health | Revert minor/digest; flush cache only if serialization changed |
| **Postgres** | `docker.io/postgres:17` (`POSTGRES_VERSION` in stable compose) | `docker-compose.yml`, `docker-compose.dev.yml`, migrate jobs | Renovate | **Low–medium** | Renovate PR; **no automatic major**; backup required for major | Config validation; backup/restore proof for major; integration tests | Revert only when on-disk format permits; else restore backup into prior major |
| **Postgres (k3s prod/staging)** | CNPG `platform-postgres` cluster image *(GitOps)* | k3s-01 `database` namespace | Platform team / CNPG operator | **Medium** | Manual coordinated upgrade | CNPG rolling upgrade procedure; app migration Jobs | CNPG rollback / PITR per platform runbook |

## Pin locations (repository)

| Path | Components referenced |
|------|----------------------|
| [`docker-compose.yml`](../docker-compose.yml) | cliproxy, litellm, cpa-manager, langfuse-web, langfuse-worker, clickhouse, minio, redis, postgres |
| [`docker-compose.dev.yml`](../docker-compose.dev.yml) | cliproxy, litellm (×2), litellm-migrate, gateway-migrate (postgres:17), cpa-manager, redis, postgres |
| [`.env.example`](../.env.example) | `CLIPROXY_IMAGE`, `POSTGRES_VERSION` |
| [`scripts/ops/generate-litellm-mock-seed.sh`](../scripts/ops/generate-litellm-mock-seed.sh) | `LITELLM_IMAGE` default |
| [`docs/CICD_PHASE2_CD_K3S.md`](CICD_PHASE2_CD_K3S.md) | k3s prod image mapping (GitOps handoff) |
| [`docs/CICD_PHASE2_STAGING.md`](CICD_PHASE2_STAGING.md) | k3s staging image mapping (GitOps handoff) |
| [`docs/ops/RUNBOOK.md`](ops/RUNBOOK.md) | Operator upgrade notes (legacy; superseded by #417 playbook) |

## Kubernetes / GitOps handoff (k3s-01)

Production and staging manifests live in the external **k3s-01** GitOps repo. ai-gateway Renovate
PRs update **compose pins in this repo**; production image promotion still flows through
[`promote-k3s-images.yml`](../.github/workflows/promote-k3s-images.yml) (#415) after staging
validation.

| Component | k3s object (prod) | Image registry / name | Notes |
|-----------|-------------------|----------------------|-------|
| cliproxy | Deployment + PVC | Nexus `cli-proxy-api` | Digest pinned in overlay; OAuth PVC |
| litellm | Deployment | `ghcr.io/berriai/litellm` | Match compose digest after Renovate merge |
| cpa-manager | Deployment + PVC | `seakee/cpa-manager` | Usage SQLite PVC |
| langfuse-web | Deployment + Ingress | `langfuse/langfuse` | Keep version aligned with worker |
| langfuse-worker | Deployment | `langfuse/langfuse-worker` | Keep version aligned with web |
| clickhouse | StatefulSet + PVC | `clickhouse/clickhouse-server` | App-scoped data |
| minio | StatefulSet + PVC | `cgr.dev/chainguard/minio` | Langfuse object store |
| postgres | — | CNPG `platform-postgres-rw` | Shared cluster; not a container pin in overlay |
| redis | — | `redis.database.svc` | Shared platform Redis |

Staging uses the same component set in namespace `ai-gateway-staging` with `:latest`/dev tags
for first-party images only; third-party pins should still be digest-pinned before production
promotion.

## Risk tiers and Renovate policy

Renovate configuration: [`.github/renovate.json`](../.github/renovate.json).

| Tier | Components | Renovate behavior |
|------|------------|-------------------|
| **High** | LiteLLM | Separate PR per update; `risk:high` label; digest pin; no auto-merge; PR checklist requires Gate A/B + staging `--full` |
| **High (excluded)** | CLIProxy / cliproxy | **Disabled in Renovate** — weekly upstream-track publishes Nexus candidates (#11); promotion via #415 |
| **Medium** | CPA-Manager, Langfuse (web+worker), ClickHouse, MinIO | Grouped where safe; no auto-merge; `risk:medium`; majors separated for storage/DB-adjacent images |
| **Low–medium** | Redis, Postgres | Patch/minor grouping allowed; Postgres **major updates disabled** in Renovate (manual migration review) |

Every Renovate PR must include in its body (via Renovate template):

1. Old and new tag/digest  
2. Release-note link / version range  
3. Migration or config changes noted in upstream release notes  
4. Required gates (from table above)  
5. Rollback target (previous digest/tag)

Unknown migration reversibility **blocks** production promotion.

## Floating pins (staging-only or discovery)

These references resolve to a moving tag today. Renovate is configured to propose digest pins;
until pinned, treat them as **discovery inputs** — not production promotion sources.

| Reference | Location | Action |
|-----------|----------|--------|
| `langfuse/langfuse:3` | `docker-compose.yml` | Renovate → pin digest; keep web/worker on same tag |
| `langfuse/langfuse-worker:3` | `docker-compose.yml` | Same group as web |
| `clickhouse/clickhouse-server` (no tag) | `docker-compose.yml` | Renovate → pin digest + tag |
| `cgr.dev/chainguard/minio` (no tag) | `docker-compose.yml` | Renovate → pin digest + tag |
| `redis:7` | compose files | Acceptable major pin; Renovate patch/minor within v7 |
| `postgres:17` / `${POSTGRES_VERSION:-17}` | compose files | Major bump requires manual issue + backup drill |

## Out of scope (first-party)

| Image | Built from | Promotion |
|-------|------------|-----------|
| `gateway-engine` | `services/gateway-engine/Dockerfile` | CI → Nexus → k3s promote workflow |
| `docs-server` | `services/docs-server/Dockerfile` | Same |
| `credential-prober` | `services/credential-prober/Dockerfile` | Same |

## Related issues

| Issue | Role |
|-------|------|
| #414 | Design spec and plan (parent of this inventory) |
| #415 | k3s image promote workflow (do not modify in #416) |
| #417 | Per-component update playbook (`docs/ops/DEPENDENCY_UPDATES.md`) |
| #418 | Cliproxy cutover (depends on CLIProxyAPI #13 + quota image) |
