# Runbook — CLIProxy upstream-patch cutover (#418) + fork/Management-Center retirement (#419)

Operator runbook for the two ops-only children of epic
[#413](https://github.com/echoares-lab/ai-gateway/issues/413):

- [#418](https://github.com/echoares-lab/ai-gateway/issues/418) — staging pin →
  deep-smoke → production promote for the upstream-based cliproxy image.
- [#419](https://github.com/echoares-lab/ai-gateway/issues/419) — archive
  `Cli-Proxy-API-Management-Center` and prune stale CLIProxy fork branches.

This runbook records the **exact operator commands**, the **current pins**, and the
**rollback pins** so an operator with cluster/registry/GitHub credentials can execute
the cutover in one pass. It exists because these steps cannot run from the Cursor Cloud
VM (no `kubectl`, OpenBao, Nexus, or write access to `k3s-01` / `CLIProxyAPI` — see
[Preconditions & known blockers](#preconditions--known-blockers)).

Design/spec references:

- [`docs/CICD_PHASE2_STAGING.md`](../CICD_PHASE2_STAGING.md) § *Promotion from staging to prod*
- [`docs/CICD_PHASE2_CD_K3S.md`](../CICD_PHASE2_CD_K3S.md) § *Verification*, § *Release identity and image promotion*
- [`docs/superpowers/plans/2026-07-17-cliproxy-upstream-patch-dep-updates.md`](../superpowers/plans/2026-07-17-cliproxy-upstream-patch-dep-updates.md) Task 7 / Task 8
- [`docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md`](../superpowers/specs/2026-07-17-staging-deep-smoke-design.md)

---

## Preconditions & known blockers

Do **not** start the cutover until all of these hold. Each was verified unmet from the
Cursor Cloud VM on 2026-07-17 (see `.orchestrate/ops-cutover-subplan/BLOCKER.md`).

| # | Precondition for #418/#419 | Status as of 2026-07-17 | How to verify it is ready |
|---|---|---|---|
| P1 | **Upstream+quota candidate image exists in Nexus** (CLIProxyAPI #12/#13/#11 landed, Nexus CI published an immutable tag/digest). | ❌ Not ready. `echoares-lab/CLIProxyAPI` returns 404 from this environment; no candidate published. This is the hard blocker for #418. | `python3 scripts/k3s/resolve_image_digest.py --reference <candidate-tag>` resolves to a `sha256:` digest against Nexus. |
| P2 | **Promote gate wired on `main`** (#415). | ✅ Landed. PR [#422](https://github.com/echoares-lab/ai-gateway/pull/422) merged to `main` (`7002949`); `scripts/k3s/resolve_image_digest.py` + digest requirement in `promote_k3s_images.py` present. | `git show origin/main:scripts/k3s/resolve_image_digest.py` |
| P3 | **CI secrets configured** so the auto/dispatch promote path does not fail closed: `CLIPROXY_CANDIDATE_TAG` (immutable, not `latest`/`dev`), `NEXUS_USERNAME`, `NEXUS_PASSWORD`, `DEEP_SMOKE_STAGING_API_KEY`, `K3S_KUBECONFIG`, and `K3S_GITOPS_TOKEN` **or** `GH_PAT_AUTO_APPROVE` (contents:write + pull-requests:write on `k3s-01`). Optional `DEEP_SMOKE_STAGING_ADMIN_KEY`. | ⚠️ Unverified from VM (repo secrets not readable). | `gh secret list --repo echoares-lab/ai-gateway` |
| P4 | **Operator has cluster + registry access**: `kubectl` context for `k3s-01`, OpenBao read for `staging|prod/workloads/ai-gateway/*`, Nexus pull, and write access to the `echoares-lab/k3s-01` GitOps repo. | ❌ None present in the Cloud VM. | `kubectl --context <k3s-01> get ns ai-gateway ai-gateway-staging`; `gh repo view echoares-lab/k3s-01` |
| P5 | **(#419 only) Maintainer/admin GitHub token** with admin on `echoares-lab/Cli-Proxy-API-Management-Center` (to archive) and push/delete on the fork repo (to prune branches). | ❌ Cloud VM token is scoped read-only to `ai-gateway` only. | `gh api repos/echoares-lab/Cli-Proxy-API-Management-Center -q .permissions` |

If P1 is unmet, **stop**: there is nothing valid to promote and freezing on `6cf6e68`
is correct. #419 depends on a successful #418, so it stays blocked until then.

---

## Current pins (source of truth for rollback)

| Component | Where | Current value | Notes |
|---|---|---|---|
| cliproxy (compose default) | `docker-compose.yml`, `docker-compose.dev.yml`, `.env.example` (`CLIPROXY_IMAGE`) | `nexus-docker.infra.plexplease.com/cli-proxy-api:6cf6e68` | Frozen fork tag. Update to the validated immutable version/digest **only** per #418 scope. |
| cliproxy (prod k3s-01) | `k3s-01` GitOps `kubernetes/workloads/home/ai-gateway/overlays/k3s-01/kustomization.yaml` → `images:` `cli-proxy-api` | **Live digest — capture in Step 0** | ArgoCD-synced. This is the authoritative prod rollback digest. |
| cliproxy (staging k3s-01) | `k3s-01` GitOps `.../overlays/staging/…` | `cli-proxy-api:dev` (fast-moving) | Staging floats; prod advances by pinning a staging-validated digest. |

> **Rollback pin rule:** the previous prod `cli-proxy-api` digest recorded in Step 0 is
> the N-1 rollback target. Never delete rollback tags/SHAs (`6cf6e68` and the captured
> prod digest) as part of #419 branch pruning.

---

## #418 — Staging → production cliproxy cutover

Aligns with plan Task 7 and `CICD_PHASE2_STAGING.md` § *Promotion*.

### Step 0 — Capture rollback state (do this first, always)

Record these into the #413/#418 closeout **before** changing any pin:

```bash
# Prod cliproxy digest currently serving traffic (N-1 rollback target):
kubectl --context <k3s-01> -n ai-gateway get deploy cliproxy \
  -o jsonpath='{.spec.template.spec.containers[*].image}'; echo
kubectl --context <k3s-01> -n ai-gateway get pods -l app=cliproxy \
  -o jsonpath='{range .items[*]}{.status.containerStatuses[*].imageID}{"\n"}{end}'

# Pinned digest in the GitOps overlay (authoritative rollback pin):
grep -A2 'name: cli-proxy-api' \
  <k3s-01>/kubernetes/workloads/home/ai-gateway/overlays/k3s-01/kustomization.yaml

# ArgoCD revisions (for both apps):
argocd app get ai-gateway         -o wide   # or: kubectl -n argocd get application ai-gateway -o jsonpath='{.status.sync.revision}'
argocd app get ai-gateway-staging -o wide

# Confirm OpenBao CLIProxy OAuth auth archive is still valid (do NOT print secret):
kubectl --context <k3s-01> -n ai-gateway get pods -l app=cliproxy \
  -o jsonpath='{.items[0].spec.volumes[?(@.name)].name}'   # PVC present
# (auth PVC is seeded from staging|prod/workloads/ai-gateway/cliproxy_auth_tar_b64 only-if-empty)
```

**Record:** prev prod digest = `sha256:…`, staging Argo rev, prod Argo rev, prev `6cf6e68`.

### Step 1 — Resolve the candidate to an immutable digest

```bash
# From an ai-gateway checkout on main; needs NEXUS_USERNAME / NEXUS_PASSWORD in env.
python3 scripts/k3s/resolve_image_digest.py --reference <CLIPROXY_CANDIDATE_TAG>
# → sha256:<candidate-digest>   (rejects latest/dev/staging/main/prod and bare tags)
```

Mutable tags and missing refs are rejected by design. Save the digest as
`CANDIDATE_DIGEST`.

### Step 2 — Pin staging to the candidate & wait for sync

Staging normally floats `cli-proxy-api:dev`; for the cutover drill, pin staging to the
exact candidate so the deep-smoke validates the promotable artifact:

```bash
# In the k3s-01 GitOps repo, staging overlay:
python3 <ai-gateway>/scripts/k3s/promote_k3s_images.py \
  --k3s-repo <k3s-01> \
  --overlay kubernetes/workloads/home/ai-gateway/overlays/staging/kustomization.yaml \
  --cliproxy "sha256:$CANDIDATE_DIGEST"
kubectl kustomize <k3s-01>/kubernetes/workloads/home/ai-gateway/overlays/staging >/dev/null
# commit + PR to k3s-01 (base: production), merge, then:
argocd app sync ai-gateway-staging && argocd app wait ai-gateway-staging --health
kubectl --context <k3s-01> -n ai-gateway-staging rollout status deploy/cliproxy
```

> If the staging overlay does not expose a separate promote target, set staging's
> `cli-proxy-api` pin by hand to `digest: sha256:$CANDIDATE_DIGEST` and sync. The
> invariant is: **the digest deep-smoked is the digest promoted to prod.**

### Step 3 — Staging deep-smoke `--full` (the promote gate)

```bash
DEEP_SMOKE_EXPECT_GIT_SHA=<candidate-git-sha> \
  ./scripts/ops/deep-smoke.sh --env staging --full
```

Must be green. `--full` asserts (see `deep-smoke.sh` header / `deep_smoke.py`):
health/ready/version/models, tagged completions, SSE streaming, claude/gpt/gemini
provider allowlist, read-mostly admin checks including **OpenAPI-hardened
`GET /admin/quota/status`** (issue #403 contract + `live_status` enums), cluster Jobs
not Failed, and a `LiteLLM_SpendLogs` DB side-effect row. On staging, Jobs and SpendLogs
are **hard** requirements (missing kubectl/DB = FAIL). Use `--strict` to fail on soft
warnings (e.g. missing Langfuse creds).

> CI equivalent (preferred once P3 secrets exist): the promote workflow runs this gate
> automatically — see Step 5. Do not open the prod pin PR until this is green.

### Step 4 — Rollback drill (N → N-1 → N), required by plan Task 7

Prove rollback works before touching prod:

```bash
# Roll staging back to N-1 (prev digest from Step 0), sync, re-smoke:
python3 <ai-gateway>/scripts/k3s/promote_k3s_images.py --k3s-repo <k3s-01> \
  --overlay .../overlays/staging/kustomization.yaml --cliproxy "sha256:$PREV_DIGEST"
argocd app sync ai-gateway-staging && argocd app wait ai-gateway-staging --health
./scripts/ops/deep-smoke.sh --env staging --full         # N-1 green

# Restore N (candidate), sync, re-smoke:
python3 <ai-gateway>/scripts/k3s/promote_k3s_images.py --k3s-repo <k3s-01> \
  --overlay .../overlays/staging/kustomization.yaml --cliproxy "sha256:$CANDIDATE_DIGEST"
argocd app sync ai-gateway-staging && argocd app wait ai-gateway-staging --health
./scripts/ops/deep-smoke.sh --env staging --full         # N green
```

Attach all three deep-smoke results (N, N-1, N) to #413. Prefer a staging soak ≥1 day
before prod (#418 execution notes: High risk).

### Step 5 — Promote the exact tested digest to production

**Preferred — gated CI workflow** (`.github/workflows/promote-k3s-images.yml`):

```bash
gh workflow run promote-k3s-images.yml --repo echoares-lab/ai-gateway \
  -f cliproxy_digest="sha256:$CANDIDATE_DIGEST"
# The workflow: resolves/validates the digest → runs staging deep-smoke --full →
# opens a one-commit PR on echoares-lab/k3s-01 (base: production) pinning the digest.
# Never use -f skip_deep_smoke=true except a declared emergency (auto path never skips).
```

**Manual fallback** (gate not usable / emergency), producing the same k3s-01 PR:

```bash
python3 <ai-gateway>/scripts/k3s/promote_k3s_images.py \
  --k3s-repo <k3s-01> --cliproxy "sha256:$CANDIDATE_DIGEST"
kubectl kustomize <k3s-01>/kubernetes/workloads/home/ai-gateway/overlays/k3s-01 >/dev/null
# commit + PR on k3s-01 (base: production); paste the Step 3 deep-smoke summary in the body.
```

Merge the k3s-01 PR only with staging `--full` green. ArgoCD syncs the pinned digest into
`ai-gateway`.

### Step 6 — Production Gate D (thin) + closeout

```bash
argocd app sync ai-gateway && argocd app wait ai-gateway --health
kubectl --context <k3s-01> -n ai-gateway get pods -l app=cliproxy \
  -o jsonpath='{range .items[*]}{.status.containerStatuses[*].imageID}{"\n"}{end}'  # == CANDIDATE_DIGEST

./cliproxy-setup.sh health
./cliproxy-setup.sh test claude-sonnet-4-5-20250929
./cliproxy-setup.sh test gemini-3-flash
./cliproxy-setup.sh test gpt-5-4
./cliproxy-setup.sh quota-summary
# Optional incident-only prod probe: ./scripts/ops/deep-smoke.sh --env prod --quick
```

**Closeout on #413/#418 must record:**

- New cliproxy digest `sha256:$CANDIDATE_DIGEST` + its upstream git SHA and the two quota patch SHAs.
- **Rollback pin** = previous prod digest `sha256:$PREV_DIGEST` (from Step 0) and frozen `6cf6e68`.
- Staging + prod ArgoCD revisions before/after.
- N → N-1 → N rollback drill links; Gate D output.
- Confirmation the CLIProxy OAuth auth archive/PVC remains valid.

### Emergency rollback (if prod cutover misbehaves)

```bash
python3 <ai-gateway>/scripts/k3s/promote_k3s_images.py \
  --k3s-repo <k3s-01> --cliproxy "sha256:$PREV_DIGEST"   # re-pin N-1
# PR to k3s-01 (base: production), merge, then:
argocd app sync ai-gateway && argocd app wait ai-gateway --health
./cliproxy-setup.sh health && ./cliproxy-setup.sh test gpt-5-4
```

---

## #419 — Archive Management-Center + prune fork branches

**Do not start until #418 prod cutover is verified green (Step 6).** Docs-only in this
repo; the repo-archive and branch-delete actions require a maintainer token (P5).

### Step A — Confirm CPA-Manager fully replaces Management-Center

Already true in this repo: `docker-compose.yml` runs `image: seakee/cpa-manager:1.5.5`
(service `cpa-manager`, port 18317), and `CLAUDE.md` states the `Cli-Proxy-API-Management-Center`
repo is no longer deployed separately. Confirm no live deployment references the old repo
(k3s-01 overlays + compose) before archiving.

### Step B — Archive the obsolete repository (maintainer token required)

```bash
# Verify it is dead surface (no ArgoCD app, no compose service points at it), then:
gh repo archive echoares-lab/Cli-Proxy-API-Management-Center --yes
gh repo view echoares-lab/Cli-Proxy-API-Management-Center --json isArchived   # → true
```

Update any docs that still point operators at it separately (grep first):

```bash
grep -rn "Cli-Proxy-API-Management-Center\|Management-Center" docs/ AGENTS.md CLAUDE.md
```

Current references to adjust: `CLAUDE.md:126` (already says "no longer deployed
separately" — keep, add archived note), `docs/ROADMAP.md:77` (roadmap entry), and the
plan checklist item. Also update the fork-build instructions that still say build cliproxy
from the fork `dev` branch: `CLAUDE.md:179` and `CLAUDE.md:198` (`/home/dev/repos/CLIProxyAPI` `dev`)
should reference the upstream+patch branch / promoted Nexus digest once #418 lands.

### Step C — Inventory and prune stale fork branches (maintainer token; keep rollback tags)

```bash
# In the CLIProxyAPI fork checkout:
git fetch --all --prune
git branch -a --sort=-committerdate     # inventory patch/* and frozen dev
git tag -l                               # confirm rollback tags exist first

# Only after cutover verified AND rollback tags/SHAs preserved:
#   - delete replaced patch/* branches and the frozen dev branch
#   - KEEP every immutable rollback tag/SHA (6cf6e68 and the prod digest's source SHA)
git push origin --delete <stale-patch-branch>   # per branch, only if truly replaced
```

Record the deleted branch names + their tip SHAs in the #419 closeout as "rollback-only,
preserved as tag/SHA." **Never delete a tag or SHA used as a rollback pin.**

### Step D — Docs/link checks + closeout

```bash
grep -rn "Cli-Proxy-API-Management-Center\|from fork \`dev\`" docs/ AGENTS.md CLAUDE.md   # expect none stale
```

Commit docs: `chore(ops): retire obsolete cliproxy fork surfaces`. Reference the cleanup
in the epic #413 closeout and move the roadmap entry to Completed.
