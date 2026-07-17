# BLOCKER — ops-cutover-subplan (#418 / #419)

Recorded 2026-07-17 from the Cursor Cloud VM. All checks are reproducible one-liners.
The scoped sub-goal directs: *"if kubectl/OpenBao/Nexus are missing in the cloud VM,
produce a complete runbook handoff with digests/rollback and stop without fake success."*
This file is the evidence; the runbook is `docs/ops/RUNBOOK_CLIPROXY_CUTOVER.md`.

## B1 — Upstream+quota cliproxy candidate does not exist (hard blocker for #418)

`echoares-lab/CLIProxyAPI` is unreachable, so CLIProxyAPI #12/#13/#11 (the quota
foundation) have not shipped a candidate image. #418 has nothing valid to promote.

```
$ gh repo view echoares-lab/CLIProxyAPI --json name
GraphQL: Could not resolve to a Repository with the name 'echoares-lab/CLIProxyAPI'. (repository)
```

Corroborated by upstream `cliproxy-fork-subplan` handoff (blocked: repo 404, no runtime).
The frozen fork image `cli-proxy-api:6cf6e68` remains the correct pin until a candidate
exists.

## B2 — No cluster / registry / GitOps access (blocks #418 execution)

- `echoares-lab/k3s-01` GitOps repo returns 404 → cannot open the promote PR from here.
- No `kubectl`, OpenBao, Nexus, or ArgoCD in the VM → cannot pin staging, run deep-smoke,
  promote, or run Gate D. (AGENTS.md "Cursor Cloud specific instructions" confirms the
  VM has no Docker daemon and no provider OAuth; real-provider Gate C/D are not runnable.)

```
$ gh repo view echoares-lab/k3s-01 --json name
GraphQL: Could not resolve to a Repository with the name 'echoares-lab/k3s-01'. (repository)
$ command -v kubectl argocd; echo "exit=$?"     # none found
```

## B3 — GitHub token read-only, scoped to ai-gateway only (blocks #419)

Cannot archive `Cli-Proxy-API-Management-Center` (exists, not archived) or push/delete
fork branches.

```
$ gh api installation/repositories -q '.repository_selection, .repositories[].full_name'
selected
echoares-lab/ai-gateway
$ gh repo view echoares-lab/Cli-Proxy-API-Management-Center --json isArchived
{"isArchived":false}
```

## B4 — No orchestration runtime (cannot spawn workers/verifiers)

```
$ command -v bun; echo "bun exit=$?"            # NO BUN (exit 1)
$ printf 'CURSOR_API_KEY set: %s\n' "${CURSOR_API_KEY:+yes}"   # (empty -> unset)
```

`bun cli.ts run` cannot execute and the Cursor SDK cannot create cloud agents, so the
decomposition in `plan.json` (cutover worker → verifier → retire-fork worker) could not
be dispatched. Even if it could, workers inherit the same B1–B3 credential wall.

## Precondition that IS met

Promote gate #415 landed on `main` (PR #422 merged, `7002949`):
`scripts/k3s/resolve_image_digest.py` and the cliproxy digest requirement in
`scripts/k3s/promote_k3s_images.py` are present. So the *tooling* for #418 is ready; only
the candidate image + operator credentials are missing.

## Rollback pins recorded (acceptance)

- Frozen fork tag (keep forever): `nexus-docker.infra.plexplease.com/cli-proxy-api:6cf6e68`.
- Live prod cliproxy **digest** = authoritative N-1 rollback pin — must be captured by the
  operator in Runbook Step 0 (`kubectl -n ai-gateway get deploy cliproxy -o jsonpath=...`
  and the `cli-proxy-api` entry in the k3s-01 prod overlay `kustomization.yaml`). Not
  resolvable from this VM (no cluster/registry access).
- Rule: #419 branch pruning must preserve `6cf6e68` and the prod digest's source SHA/tag.

## To unblock (hand to parent / operator)

1. Ship CLIProxyAPI #12/#13/#11 and publish an immutable Nexus candidate (B1).
2. Configure repo secrets `CLIPROXY_CANDIDATE_TAG`, `NEXUS_USERNAME`, `NEXUS_PASSWORD`,
   `DEEP_SMOKE_STAGING_API_KEY`, `K3S_KUBECONFIG`, `K3S_GITOPS_TOKEN`/`GH_PAT_AUTO_APPROVE`.
3. Run the runbook from an environment with kubectl + OpenBao + Nexus + k3s-01 write (B2).
4. For #419, use a maintainer token with admin on Management-Center and delete on the fork (B3).
