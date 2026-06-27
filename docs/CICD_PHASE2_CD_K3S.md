# CI/CD Phase 2 — Continuous Deployment to k3s

Phase 1 (CI migration to ARC runners + Nexus) is complete. This document specifies
**Phase 2: deploying the ai-gateway stack onto the `k3s-01` cluster via ArgoCD/Kustomize**,
replacing the hand-run `docker compose` host.

Authoritative manifests live in the **`k3s-01`** repo under
`kubernetes/workloads/home/ai-gateway/overlays/k3s-01/`. This file is the design/spec kept
in the application repo for reference.

## Confirmed decisions (from Phase 1 brainstorming)

| Topic | Decision |
|---|---|
| Postgres/Redis | **Shared central** — reuse `platform-postgres` (CNPG) + `redis` in the `database` namespace; add `litellm` and `langfuse` databases |
| Langfuse/ClickHouse/MinIO | **Full stack in-cluster** — ClickHouse + MinIO app-scoped in the `ai-gateway` namespace |
| Images | Pull from **Nexus** (`nexus-docker.infra.plexplease.com/ai-gateway/*`, `/cli-proxy-api`) |
| Secrets | **OpenBao** `prod/workloads/ai-gateway/*` via External Secrets |
| Ingress | Traefik + cert-manager at `gateway.infra.plexplease.com` (`letsencrypt-cloudflare`) |
| Rollout | Manifests track `:latest` from Nexus initially; pin/ImageUpdater later |

## Architecture on k3s

```
Traefik ingress (gateway.infra.plexplease.com, TLS via cert-manager)
  └─► gateway-engine (Deployment, :4000)         ← public entrypoint
        └─► litellm (Deployment, :4000 internal)
              └─► cliproxy (Deployment, :8317, fork image + OAuth PVC)
        ├─► redis.database.svc (shared)
        └─► litellm-config.yaml (ConfigMap)
Observability (app-scoped in ai-gateway ns):
  langfuse-web (:3000, ingress langfuse.infra.plexplease.com) + langfuse-worker
    └─► clickhouse (StatefulSet, storage-fast) + minio (StatefulSet, storage-fast)
    └─► platform-postgres-rw.database.svc (langfuse DB) + redis.database.svc
Shared DB (database ns): platform-postgres (CNPG) — databases: litellm, langfuse
Support: credential-prober (Deployment), docs-server (Deployment), cpa-manager (Deployment)
```

## Components → Kubernetes objects

| compose service | k8s object | image source | notes |
|---|---|---|---|
| gateway-engine | Deployment + Service + Ingress | Nexus `ai-gateway/gateway-engine` | public entrypoint; reads litellm-config ConfigMap |
| litellm | Deployment + Service | `ghcr.io/berriai/litellm` (pinned digest) | DB = `litellm` on platform-postgres |
| cliproxy | Deployment + Service + **PVC** | Nexus `cli-proxy-api` | OAuth token PVC seeded from OpenBao |
| docs-server | Deployment + Service (+ Ingress opt.) | Nexus `ai-gateway/docs-server` | |
| credential-prober | Deployment | Nexus `ai-gateway/credential-prober` | posts to gateway-engine |
| cpa-manager | Deployment + Service + PVC | `seakee/cpa-manager` | usage SQLite PVC |
| clickhouse | StatefulSet + Service + PVC | `clickhouse/clickhouse-server` | `storage-fast`, app-scoped |
| minio | StatefulSet + Service + PVC | `chainguard/minio` | `storage-fast`, app-scoped; bucket `langfuse` |
| langfuse-web | Deployment + Service + Ingress | `langfuse/langfuse:3` | |
| langfuse-worker | Deployment | `langfuse/langfuse-worker:3` | |
| postgres | — (shared) | — | use `platform-postgres-rw.database.svc:5432` |
| redis | — (shared) | — | use `redis.database.svc.cluster.local:6379` |

## Databases on the shared CNPG cluster

The CNPG `Database` CRD is **not** installed, so create databases with an idempotent
**bootstrap Job** (ArgoCD `PreSync` hook) that connects to `platform-postgres-rw` as the
superuser (secret `platform-postgres-superuser` in `database` ns, mirrored via ExternalSecret
or referenced cross-namespace) and runs:

```sql
CREATE DATABASE litellm;   -- idempotent guard via psql \gexec / DO block
CREATE DATABASE langfuse;
-- create app role(s) with scoped grants; store password in OpenBao
```

Then **migration Jobs** (ArgoCD `Sync` hooks, after the DBs exist):
- `litellm-migrate`: `prisma migrate deploy` (litellm image) against the `litellm` DB.
- `gateway-migrate`: apply `db/migrations/*.sql` (reuse `db/apply-migrations.sh` logic) against `litellm`.

## Secrets (OpenBao → External Secrets)

Path `prod/workloads/ai-gateway/*`, surfaced as k8s Secrets in the `ai-gateway` namespace via
`ExternalSecret` (ClusterSecretStore `openbao`). Keys: `litellm_master_key`,
`gateway_engine_admin_key`, `cliproxy_api_key`, `cliproxy_management_key`, `litellm_db_url`,
`langfuse_db_url`, `redis_auth`, `clickhouse_password`, `minio_root_user`,
`minio_root_password`, `nextauth_secret`, `langfuse_salt`, `langfuse_encryption_key`,
plus optional search/MCP keys. Plus `cliproxy_auth_tar_b64` for the CLIProxy OAuth seed.

## CLIProxy OAuth token persistence

CLIProxy refreshes OAuth tokens at runtime and writes them back to `~/.cli-proxy-api`. On k8s:
- A `PersistentVolumeClaim` (`storage-fast`, RWO) mounted at `/home/dev/.cli-proxy-api`.
- An **initContainer** seeds the PVC from the `cliproxy_auth_tar_b64` secret **only if empty**
  (so runtime-refreshed tokens are never clobbered on restart).
- **Open follow-up:** periodic write-back of refreshed tokens to OpenBao (sidecar/CronJob).
  Deferred; tokens persist on the PVC in the interim.

## Ingress / public entrypoint

- `gateway.infra.plexplease.com` → `gateway-engine:4000` (Traefik, `letsencrypt-cloudflare`).
- `langfuse.infra.plexplease.com` → `langfuse-web:3000` (optional).
- The existing external Cloudflare tunnel to `gateway.example.com` is **out of scope** here;
  repoint it at the k8s ingress once the deployment is validated.

## GitOps wiring

- New dir `kubernetes/workloads/home/ai-gateway/overlays/k3s-01/` (namespace, deployments,
  statefulsets, services, ingress, externalsecrets, configmap, jobs, kustomization).
- Register it in `kubernetes/clusters/k3s-01/kustomization.yaml` (app-of-apps).
- `litellm-config.yaml` shipped as a ConfigMap (generated from the repo file).
- Namespace `ai-gateway` labeled `app.kubernetes.io/managed-by: argocd`.

## Verification

1. ArgoCD `k3s-01` app Synced/Healthy; `ai-gateway` namespace resources reconciled.
2. Bootstrap + migration Jobs complete; `litellm` and `langfuse` databases exist on
   `platform-postgres`.
3. `kubectl -n ai-gateway get pods` all Ready (gateway-engine, litellm, cliproxy, docs-server,
   credential-prober, clickhouse, minio, langfuse-web/worker, cpa-manager).
4. `curl https://gateway.infra.plexplease.com/health` → ok; `/v1/models` returns the catalog.
5. Smoke a model end-to-end (e.g. `claude-sonnet-4-6`) through the ingress with the master key.
6. `langfuse.infra.plexplease.com` loads; traces appear.

## Out of scope / follow-ups
- OAuth token write-back to OpenBao.
- External Cloudflare public-edge repoint.
- Image rollout automation (ArgoCD Image Updater or CI tag-commit) — initially `:latest`.
- Decommission the old `docker compose` host + classic self-hosted runner (after burn-in).
