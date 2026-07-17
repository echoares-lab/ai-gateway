# CI/CD Phase 2 — Staging Deployment to k3s

This document specifies a **staging** deployment of the ai-gateway stack on the `k3s-01`
cluster. It mirrors the production design in [`CICD_PHASE2_CD_K3S.md`](CICD_PHASE2_CD_K3S.md)
but targets a fully isolated staging environment so changes can be validated on real
infrastructure before promotion to prod.

As with production, the **authoritative manifests live in the external `k3s-01` GitOps repo**
(under `kubernetes/workloads/home/ai-gateway/overlays/staging/`). This repo
(`echoares-lab/ai-gateway`) holds the **design spec + config-generation tooling** that the
GitOps repo consumes — it does **not** hold the live cluster manifests. Nothing here reaches
a cluster directly.

## Isolation model — staging vs. prod

Staging shares only the physical cluster and the central Postgres/Redis platform services.
Everything addressable is namespaced or renamed so a staging rollout can never disturb the
production `ai-gateway` namespace or its live traffic.

| Concern | Production | Staging |
|---|---|---|
| Namespace | `ai-gateway` | **`ai-gateway-staging`** |
| OpenBao secrets path | `prod/workloads/ai-gateway/*` | **`staging/workloads/ai-gateway/*`** |
| Gateway ingress host | `gateway.infra.plexplease.com` | **`gateway-staging.infra.plexplease.com`** |
| Langfuse ingress host | `langfuse.infra.plexplease.com` | `langfuse-staging.infra.plexplease.com` |
| LiteLLM database | `litellm` | **`litellm_staging`** |
| Langfuse database | `langfuse` | **`langfuse_staging`** |
| Images | Nexus pinned/`:latest` | **`:latest` / dev tags** (fast-moving) |
| ArgoCD app | `ai-gateway` (k3s-01) | `ai-gateway-staging` (k3s-01) |

## Architecture on k3s (staging)

```
Traefik ingress (gateway-staging.infra.plexplease.com, TLS via cert-manager)
  └─► gateway-engine (Deployment, :4000)         ← public entrypoint (staging)
        └─► litellm (Deployment, :4000 internal)
              └─► cliproxy (Deployment, :8317, fork image + OAuth PVC)
        ├─► redis.database.svc (shared platform-redis)
        └─► litellm-config.yaml (ConfigMap: litellm-config in ai-gateway-staging)
Observability (app-scoped in ai-gateway-staging ns):
  langfuse-web (:3000, ingress langfuse-staging.infra.plexplease.com) + langfuse-worker
    └─► clickhouse (StatefulSet, storage-fast) + minio (StatefulSet, storage-fast)
    └─► platform-postgres-rw.database.svc (langfuse_staging DB) + redis.database.svc
Shared DB (database ns): platform-postgres (CNPG) — databases: litellm_staging, langfuse_staging
Support: credential-prober, docs-server, cpa-manager (Deployments)
```

The component → Kubernetes object mapping is identical to production
([`CICD_PHASE2_CD_K3S.md` § Components → Kubernetes objects](CICD_PHASE2_CD_K3S.md#components--kubernetes-objects));
only the namespace, hostnames, database names, secrets path, and image tags differ.

## Namespace

- Namespace: **`ai-gateway-staging`**, labeled `app.kubernetes.io/managed-by: argocd`.
- All app-scoped objects (ClickHouse, MinIO, Langfuse, cpa-manager PVCs, ConfigMaps,
  ExternalSecrets) live inside this namespace. No object is shared with `ai-gateway`.
- The generated ConfigMap (`litellm-config`) is namespaced to `ai-gateway-staging`
  (see [Config generation](#config-generation)).

## Databases on the shared CNPG cluster

Staging reuses the central `platform-postgres` (CNPG) cluster in the `database` namespace but
with **separate databases** so staging data never mixes with prod:

```sql
CREATE DATABASE litellm_staging;    -- idempotent guard via psql \gexec / DO block
CREATE DATABASE langfuse_staging;
-- create a staging app role with scoped grants; store its password in OpenBao
```

Wiring mirrors production ([`CICD_PHASE2_CD_K3S.md` § Databases](CICD_PHASE2_CD_K3S.md#databases-on-the-shared-cnpg-cluster)):

- A bootstrap **Job** (ArgoCD `PreSync` hook) connects to `platform-postgres-rw` as the
  superuser and creates `litellm_staging` + `langfuse_staging` idempotently.
- Migration **Jobs** (ArgoCD `Sync` hooks) run after the databases exist:
  - `litellm-migrate`: `prisma migrate deploy` (litellm image) against `litellm_staging`.
  - `gateway-migrate`: apply `db/migrations/*.sql` (reuse `db/apply-migrations.sh` logic)
    against `litellm_staging`.

Redis is shared (`redis.database.svc.cluster.local:6379`); staging uses a distinct Redis
logical DB index / key prefix or auth to avoid cache-key collisions with prod.

## Secrets (OpenBao → External Secrets)

Path **`staging/workloads/ai-gateway/*`**, surfaced as k8s Secrets in the
`ai-gateway-staging` namespace via `ExternalSecret` (ClusterSecretStore `openbao`). Keys match
production ([`CICD_PHASE2_CD_K3S.md` § Secrets](CICD_PHASE2_CD_K3S.md#secrets-openbao--external-secrets)):
`litellm_master_key`, `gateway_engine_admin_key`, `cliproxy_api_key`,
`cliproxy_management_key`, `litellm_db_url` (→ `litellm_staging`),
`langfuse_db_url` (→ `langfuse_staging`), `redis_auth`, `clickhouse_password`,
`minio_root_user`, `minio_root_password`, `nextauth_secret`, `langfuse_salt`,
`langfuse_encryption_key`, plus optional search/MCP keys and `cliproxy_auth_tar_b64` for the
CLIProxy OAuth seed.

Staging secrets are **independent** of prod: rotating a staging key never touches
`prod/workloads/ai-gateway/*`. The OpenBao policy for `k3s-01-external-secrets` must be
extended to read `kv/…/staging/workloads/*` (analogous to the prod grant).

## CLIProxy OAuth token persistence

Identical mechanism to production
([`CICD_PHASE2_CD_K3S.md` § CLIProxy OAuth](CICD_PHASE2_CD_K3S.md#cliproxy-oauth-token-persistence)):
a `storage-fast` RWO PVC mounted at `/home/dev/.cli-proxy-api`, seeded by an initContainer
from `cliproxy_auth_tar_b64` **only if empty**. Staging uses its own PVC and its own OAuth
seed from `staging/workloads/ai-gateway/*`, so staging token refreshes never touch prod
tokens.

## Ingress / public entrypoint

- **`gateway-staging.infra.plexplease.com`** → `gateway-engine:4000`
  (Traefik, cert-manager `letsencrypt-cloudflare`).
- `langfuse-staging.infra.plexplease.com` → `langfuse-web:3000` (optional).
- Both hosts use the `letsencrypt-cloudflare` ClusterIssuer, same as prod, but with distinct
  DNS records and certificates.
- No external Cloudflare tunnel repoint for staging — staging is reachable only via its own
  ingress host.

## Images

Staging tracks **fast-moving `:latest` / dev tags** so freshly built images land in staging
first:

- `gateway-engine`, `docs-server`, `credential-prober`: Nexus `ai-gateway/*:latest`.
- `cliproxy`: Nexus `cli-proxy-api:dev`.
- `litellm`: `ghcr.io/berriai/litellm` (staging may float ahead of the prod-pinned digest).

Because staging runs `:latest`, enable ArgoCD auto-sync (with prune) on the staging app so
new images roll out automatically; prod stays on pinned/gated rollouts.

## Config generation

The staging `litellm-config` ConfigMap is generated from this repo's `litellm-config.yaml`
using [`scripts/ops/generate-staging-configmap.sh`](../scripts/ops/generate-staging-configmap.sh):

```bash
# Render the ai-gateway-staging ConfigMap and validate the embedded YAML parses.
scripts/ops/generate-staging-configmap.sh > /tmp/litellm-config.staging.yaml
```

The script:

- Renders `litellm-config.yaml` into a ConfigMap named `litellm-config` in namespace
  `ai-gateway-staging` on stdout.
- Validates both the source YAML and the emitted block scalar re-parse cleanly (fails
  non-zero otherwise).
- Is POSIX sh + python3 (stdlib `yaml`) only — no extra dependencies.

Overridable via `LITELLM_CONFIG`, `STAGING_NAMESPACE`, and `CONFIGMAP_NAME` environment
variables. Commit the rendered manifest into the external `k3s-01` GitOps repo under the
staging overlay; ArgoCD reconciles it into the cluster.

## Verification

1. ArgoCD `ai-gateway-staging` app Synced/Healthy; `ai-gateway-staging` namespace reconciled.
2. Bootstrap + migration Jobs complete; `litellm_staging` and `langfuse_staging` databases
   exist on `platform-postgres`.
3. `kubectl -n ai-gateway-staging get pods` all Ready.
4. `curl https://gateway-staging.infra.plexplease.com/health` → ok;
   `/v1/models` returns the catalog.
5. Smoke a model end-to-end (e.g. `claude-sonnet-4-6`) through the staging ingress with the
   staging master key.
6. `langfuse-staging.infra.plexplease.com` loads; traces appear.

## Promotion from staging to prod

Staging is the pre-prod gate. The promotion flow (see also epic
[#396](https://github.com/echoares-lab/ai-gateway/issues/396) and
[`docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md`](superpowers/specs/2026-07-17-staging-deep-smoke-design.md)):

1. **Merge to `main`** in this repo — application/config changes (including
   `litellm-config.yaml`) land on `main` via PR with CI green.
2. **Build & publish** images to Nexus. Staging picks up `:latest` automatically via ArgoCD
   auto-sync.
3. **Validate on staging** — run the [Verification](#verification) steps against
   `gateway-staging.infra.plexplease.com`. Confirm health, model catalog, an end-to-end
   completion, and Langfuse traces.
4. **Deep smoke (promote gate)** — before opening the prod digest-pin PR, run the full staging
   deep-smoke from an operator machine with kubectl and DB access:

   ```bash
   ./scripts/ops/deep-smoke.sh --env staging --full
   ```

   This is the human/process promote gate: multi-API shapes, streaming, admin surfaces,
   cluster readiness, and `LiteLLM_SpendLogs` side effects that CI and thin post-merge Gate D
   do not cover. Paste the markdown summary into the GitOps PR or issue closeout.

   - **Langfuse** — best-effort / warn-only when credentials are unset; use `--strict` to
     promote warnings (including missing Langfuse) to failures.
   - **Quota** — soft check only (`GET /admin/quota/status` → 2xx + parseable JSON). Do not
     assert field contracts until the quota schema is frozen (follow-up #403).
   - **Prod quick smoke** — optional incident path only:
     `./scripts/ops/deep-smoke.sh --env prod --quick`

   Do **not** open or merge the k3s-01 digest-pin PR until staging `--full` is green.
5. **Regenerate the prod ConfigMap** from the same `litellm-config.yaml` (production's
   generator / the existing prod overlay) and open a PR in the `k3s-01` GitOps repo pinning
   the **exact digest validated by step 4**.
6. **Promote** by merging the GitOps PR: prod's ArgoCD app syncs the validated digest into the
   `ai-gateway` namespace. Prod stays on pinned digests (not `:latest`) so promotion is an
   explicit, reviewed change.
7. **Gate D on prod (thin)** — after prod sync, run the advisory post-merge smokes from
   [`CICD_PHASE2_CD_K3S.md` § Verification](CICD_PHASE2_CD_K3S.md#verification) against
   `gateway.infra.plexplease.com`. Gate D stays intentionally thin; deep coverage belongs on
   staging step 4.

The invariant: **the same commit/config validated on staging (including deep smoke) is what
gets pinned to prod.** Staging floats on `:latest`; prod advances only by pinning a
staging-validated digest.

For Gateway Engine, `VERSION` supplies the human SemVer image tag and OCI
version label, while the full Git SHA/digest remains the immutable promotion
and rollback identity. The production GitOps promotion changes that immutable
pin together with `app.kubernetes.io/version`; the runtime exposes the same
release through `GET /version`, with `display_version` in
`<semver>+sha.<short-sha>` form.
