<!-- orchestrate handoff
task: k3s-staging
branch: orch/model-discovery/k3s-staging
agentId: bc-3736cb74-54ba-4440-8b6b-d6cfa83bb7d9
runId: run-be872a8a-cf07-4797-be1d-289a376f0335
resultStatus: finished
finishedAt: 2026-07-11T09:37:19.509Z
-->

All deliverables are complete and verified. Draft PR #367 is open.

## Status
success

## Branch
`orch/model-discovery/k3s-staging`

## What I did
- **`docs/CICD_PHASE2_STAGING.md`** (new): staging overlay spec mirroring `CICD_PHASE2_CD_K3S.md` — namespace `ai-gateway-staging`, OpenBao `staging/workloads/ai-gateway/*` via External Secrets, ingress `gateway-staging.infra.plexplease.com` (Traefik + cert-manager `letsencrypt-cloudflare`), shared `platform-postgres` with `litellm_staging` + `langfuse_staging` databases, `:latest`/dev images with ArgoCD auto-sync, CLIProxy OAuth PVC seeding, and an explicit staging→prod promotion flow (validate on staging, pin the validated digest into the prod GitOps overlay).
- **`scripts/generate-staging-configmap.sh`** (new, POSIX sh + python3 stdlib `yaml`, no new deps): renders `litellm-config.yaml` into a `litellm-config` ConfigMap in namespace `ai-gateway-staging` on stdout; validates the source YAML and re-parses the emitted block scalar (fails non-zero otherwise); overridable via `LITELLM_CONFIG`/`STAGING_NAMESPACE`/`CONFIGMAP_NAME`.
- **`AGENTS.md`** + **`CLAUDE.md`**: added a "Kubernetes / k3s deployment" section to each linking both the prod (`CICD_PHASE2_CD_K3S.md`) and new staging (`CICD_PHASE2_STAGING.md`) docs plus the generator script.
- Committed, pushed, and opened draft PR #367 against `main`. Did not touch `services/**`, `litellm-config.yaml` entries, `docs/openapi/**`, or `.github/**`.

## Measurements
- `bash scripts/generate-staging-configmap.sh; echo $?`: (n/a) == `0`
- verifier assertion (namespace + embedded-YAML parse): (n/a) == `ok`
- ConfigMap round-trip fidelity `len(model_list)`: 44 == 44 (source dict `==` embedded dict)

## Verification
unit-test-verified

Ran the exact automated checks from the verification plan: the generator exits 0, the verifier assertion prints `ok` (namespace `ai-gateway-staging`, embedded YAML parses), and the embedded config is byte-faithful to the source (source dict equals embedded dict, 44 models). `sh -n` passes on the script.

## Notes, concerns, deviations, findings, thoughts, feedback
- Neither `AGENTS.md` nor `CLAUDE.md` previously had a "k3s section" (grep for k3s/kubernetes returned nothing). I created a `## Kubernetes / k3s deployment` section in each to host the link — this both satisfies the linking criterion and makes prod+staging docs discoverable.
- Branch is `orch/model-discovery/k3s-staging` as the orchestrator required; this does not match the cloud-agent `cursor/*-b7d9` template, so I set `skip_branch_prefix_check` when opening the PR.
- The repo's Aikido auto-scan rule/MCP is not available in this cloud env (no `aikido`/`scan` MCP tools; plugin skill file absent), so I could not run the mandated scan. The change is a POSIX shell script + docs with no secrets or network calls — low risk — but a maintainer may want to run the scan in CI.
- `.orchestrate/` does not exist in the tree; nothing to exclude. Only the four in-scope files are staged/committed.
- Design decision: staging tracks `:latest` with ArgoCD auto-sync while prod advances only by pinning a staging-validated digest — I made this the core promotion invariant. Adjust if the planner prefers tag-based promotion instead.

## Suggested follow-ups
- Materialize the actual staging overlay (kustomization, deployments, externalsecrets, ingress, bootstrap/migration Jobs) in the external `k3s-01` GitOps repo per this spec.
- Add a CI check (or Makefile target) that runs `scripts/generate-staging-configmap.sh` on config changes to keep the rendered staging ConfigMap in sync.
- Extend the OpenBao `k3s-01-external-secrets` policy to read `kv/…/staging/workloads/*` (called out in the doc as a prerequisite).
- Consider a parallel `generate-prod-configmap.sh` (or parameterized single script) so prod and staging ConfigMaps share one generator.