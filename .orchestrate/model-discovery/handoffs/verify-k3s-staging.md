<!-- orchestrate handoff
task: verify-k3s-staging
branch: `orch/model-discovery/k3s-staging` (verified on target branch at commit `8d3cb0f`; no verifier artifacts required beyond this handoff)
agentId: bc-7662eb98-3bb5-4c72-b938-fa4d8c5f1224
runId: run-325814c2-b5b8-44c4-991e-f95ff49cfc18
resultStatus: finished
finishedAt: 2026-07-11T09:39:04.082Z
-->

All checks pass, including negative validation. Every acceptance criterion is verified with execution evidence.

## Verification
unit-test-verified

## Target
`k3s-staging` on branch `orch/model-discovery/k3s-staging`

## Branch
`orch/model-discovery/k3s-staging` (verified on target branch at commit `8d3cb0f`; no verifier artifacts required beyond this handoff)

## Execution
- `git log --oneline` → worker commit `8d3cb0f feat(k3s): add staging deployment path and configmap generator` present on `orch/model-discovery/k3s-staging`.
- `sh -n scripts/generate-staging-configmap.sh` → exit 0 (POSIX syntax clean).
- `python3 -c "import yaml"` → PyYAML 6.0.1 available (no new deps needed).
- `bash scripts/generate-staging-configmap.sh > /tmp/staging-cm.yaml; echo $?` → **exit 0**, 1029-line ConfigMap emitted; header shows `kind: ConfigMap`, `name: litellm-config`, `namespace: ai-gateway-staging`.
- Plan's verifier assertion (`safe_load_all` → find ConfigMap → assert namespace `ai-gateway-staging` + re-parse embedded YAML) → prints **`ok`**.
- Round-trip fidelity check → source `model_list` = 44 models, embedded = 44, `src == emb` → **True** (byte-faithful embed).
- Negative test with malformed YAML (`LITELLM_CONFIG=/tmp/bad.yaml`) → **exit 1** with `not valid YAML` error (validation genuinely gates).
- Negative test with config missing `model_list` → **exit 1** with descriptive error.
- `gh pr view 367` → `{state: OPEN, isDraft: true, baseRefName: main, headRefName: orch/model-discovery/k3s-staging}`.
- `git diff --name-only d4a621b..8d3cb0f` → only 4 files: `AGENTS.md`, `CLAUDE.md`, `docs/CICD_PHASE2_STAGING.md`, `scripts/generate-staging-configmap.sh` (no `services/**`, `litellm-config.yaml` entries, `docs/openapi/**`, or `.github/**`).
- Read `docs/CICD_PHASE2_STAGING.md` (186 lines) and grepped `AGENTS.md`/`CLAUDE.md` for the doc link.

## Findings
Per acceptance criterion:
- [x] `docs/CICD_PHASE2_STAGING.md` exists and specifies namespace, OpenBao secrets path, ingress host, staging databases, images, and prod-promotion flow: **met** — namespace `ai-gateway-staging` (§Namespace), secrets `staging/workloads/ai-gateway/*` via External Secrets (§Secrets), ingress `gateway-staging.infra.plexplease.com` w/ Traefik + cert-manager letsencrypt-cloudflare (§Ingress), `litellm_staging` + `langfuse_staging` on shared platform-postgres (§Databases), `:latest`/dev images w/ ArgoCD auto-sync (§Images), and a 6-step staging→prod promotion flow with the "validated digest pinned to prod" invariant (§Promotion). Includes an explicit prod-vs-staging isolation table.
- [x] `scripts/generate-staging-configmap.sh` renders a valid k8s ConfigMap (namespace `ai-gateway-staging`) and validates embedded YAML parses: **met** — exit 0, verifier assertion prints `ok`, embedded config round-trips (44/44 models equal), and negative tests confirm it fails non-zero on broken/invalid input.
- [x] Staging doc linked from k3s sections of `AGENTS.md` and `CLAUDE.md`: **met** — both files gained a `## Kubernetes / k3s deployment` section linking `docs/CICD_PHASE2_STAGING.md` (and the prod doc + generator script). AGENTS.md L440-451, CLAUDE.md L225-243.
- [x] Draft PR against main opened: **met** — PR #367, OPEN, isDraft=true, base `main`, head `orch/model-discovery/k3s-staging`.

Verifier-specific:
- [x] Verification section includes execution evidence for all k3s-staging acceptance criteria: **met** (see Execution above).

Other findings:
- (low) The task text names the pre-existing doc `docs/CICD_PHASE2_CD_K3S.md` as the prod mirror; it exists in-tree and the staging doc cross-references it via valid relative links.
- (low) Prod isolation is thorough: distinct namespace, secrets path, both ingress hosts (gateway + langfuse), and both DB names all differ from prod — matches the plan's "gotcha".

## Notes & suggestions
- The worker's self-reported measurements reproduced exactly (exit 0, `ok`, 44==44). No discrepancies.
- Worker's noted caveat stands: Aikido auto-scan MCP is unavailable in this env, so the mandated scan could not run — low risk (POSIX shell + docs, no secrets/network), but a maintainer may want CI to scan.
- Suggested follow-up (worker-aligned): add a Makefile target / CI check that runs the generator on config changes to keep the rendered staging ConfigMap in sync; and materialize the actual overlay in the external `k3s-01` GitOps repo per the spec.