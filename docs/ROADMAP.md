# Roadmap Status

Approved coordination decisions for what agents may claim. Implementation still
follows `docs/process/REPO_IMPROVEMENT_WORKFLOW.md`: claim approved, unassigned, atomic
issues only — never parent epics, and never items that exist only in
[FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md).

| Doc | Role |
|-----|------|
| **This file** | Approved Now / Next / Parked / Completed |
| [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) | Ideas **not** approved — document only until promoted here |

Last reviewed: 2026-07-17 (Staging deep-smoke promote gate epic #396 approved under Next).

---

## Now

### Gemini CLI retirement and quota reliability

Approve coordination epic
[#386](https://github.com/echoares-lab/ai-gateway/issues/386) and its seven atomic
children. This release removes Gemini CLI from this gateway deployment while
preserving generic CLIProxy compatibility, repairs quota and credential delivery,
and introduces an isolated staging-to-production promotion path.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Staging foundation #58](https://github.com/echoares-lab/k3s-01/issues/58) | `k3s-01` | Ready; branch from `production` |
| 1 | [CLIProxy quota foundation #6](https://github.com/echoares-lab/CLIProxyAPI/issues/6) | `CLIProxyAPI` | Ready; branch from `main` |
| 1 | [Gemini CLI routing retirement #387](https://github.com/echoares-lab/ai-gateway/issues/387) | `ai-gateway` | Ready; branch from `main` |
| 2 | [Staging workloads #59](https://github.com/echoares-lab/k3s-01/issues/59) | `k3s-01` | Depends on staging foundation #58 |
| 2 | [CLIProxy quota contract #5](https://github.com/echoares-lab/CLIProxyAPI/issues/5) | `CLIProxyAPI` | Depends on quota foundation #6 |
| 3 | [Gateway quota and prober reliability #388](https://github.com/echoares-lab/ai-gateway/issues/388) | `ai-gateway` | Depends on CLIProxyAPI #5 and #387 |
| 4 | [Staging validation and production promotion #60](https://github.com/echoares-lab/k3s-01/issues/60) | `k3s-01` | Depends on all implementation issues |

Release invariants:

- one atomic issue per claim, agent, branch, external worktree, and isolated dev
  slot where a live stack is required;
- serialize changes to `litellm-config.yaml` and Gateway Engine hotspots;
- staging uses dedicated OAuth state and `staging/workloads/ai-gateway/*` secrets,
  never production credentials or token storage;
- validate immutable image digests and the merged LiteLLM config in staging, then
  promote exactly those artifacts to production;
- remove every deployment-specific `via-gcli` model, fallback, alias, seed
  reference, and operator instruction while retaining generic CLIProxy and
  database compatibility; and
- record Gate evidence, digests, ArgoCD revisions, credential archive and rollback
  references, production verification, and post-merge cleanup in issue closeouts.

The encrypted Gemini CLI credential archive is retained for seven days after
successful production verification, then deleted through a separately recorded
closeout action.

---

## Next — Staging deep-smoke promote gate

Approve coordination epic
[#396](https://github.com/echoares-lab/ai-gateway/issues/396) and its atomic
children. Staging `--full` deep-smoke is the human/process promote gate before
pinning digests to production. It covers gaps CI and thin Gate D miss (API
shapes, streaming, admin soft checks, cluster readiness, `LiteLLM_SpendLogs`).

| Order | Atomic issue | State / dependency |
|------:|--------------|--------------------|
| 0 | [ROADMAP + design/plan #397](https://github.com/echoares-lab/ai-gateway/issues/397) | Ready; docs-only |
| 1 | [`--quick` scaffold #398](https://github.com/echoares-lab/ai-gateway/issues/398) | Depends on #397 |
| 2 | [`--full` HTTP shapes #399](https://github.com/echoares-lab/ai-gateway/issues/399) | Depends on #398 |
| 2 | [Soft admin + quota #400](https://github.com/echoares-lab/ai-gateway/issues/400) | Depends on #398; soft asserts only |
| 3 | [SpendLogs + cluster #401](https://github.com/echoares-lab/ai-gateway/issues/401) | Depends on #399 |
| 3 | [Promote checklist docs #402](https://github.com/echoares-lab/ai-gateway/issues/402) | Depends on #398 |
| 4 | [CI gate promote on deep-smoke #410](https://github.com/echoares-lab/ai-gateway/issues/410) | Depends on #401 |
| 5 | [Harden quota asserts #403](https://github.com/echoares-lab/ai-gateway/issues/403) | Blocked on #400 + OpenAPI freeze |

Invariants:

- do **not** replace advisory `post-merge-gate-d.yml`;
- default `--env staging`; prod `--quick` is optional/incident-only;
- serialize `scripts/ops/deep-smoke.*`;
- keep `/admin/quota/status` checks soft until #403 (quota schema still moving).

Spec: [`docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md`](./superpowers/specs/2026-07-17-staging-deep-smoke-design.md).  
Plan: [`docs/superpowers/plans/2026-07-17-staging-deep-smoke.md`](./superpowers/plans/2026-07-17-staging-deep-smoke.md).

---

## Next — Release identity and versioning

Approve atomic implementation issue
[#379](https://github.com/echoares-lab/ai-gateway/issues/379) after this roadmap
promotion merges. The release contract keeps human readability and immutable
traceability together:

- use SemVer as the human release version and the full Git commit SHA as the
  immutable source identity;
- expose `display_version` as `<semver>+sha.<short-sha>`;
- publish OCI version/revision labels plus human-readable SemVer and immutable
  SHA tags without replacing digest-pinned promotion;
- propagate the release version through `app.kubernetes.io/version` in the
  authoritative Kubernetes deployment flow; and
- add and document a Gateway Engine `GET /version` endpoint returning `version`,
  `git_sha`, and `display_version`.

Issue #379 remains blocked and unclaimable until the roadmap-promotion PR for
[#380](https://github.com/echoares-lab/ai-gateway/issues/380) merges. Runtime,
CI, image, OpenAPI, and deployment changes belong to #379, not the promotion PR.

---

## Parked — multi-tenant / onboarding (decision unclear)

Keep these open as coordination anchors with `status:blocked`. Do **not** claim
or expand them until a tenancy decision is made and the items are promoted with
fresh child issues.

- **Multi-tenant workspace management** ([#30](https://github.com/echoares-lab/ai-gateway/issues/30))
- **Self-service onboarding** ([#34](https://github.com/echoares-lab/ai-gateway/issues/34))
- **Admin tenant/team panel** ([#109](https://github.com/echoares-lab/ai-gateway/issues/109))

Expanded tenancy scope: [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) (C-TEN-*).

---

## Completed (2026-07 wave)

### Stability Foundation ([#377](https://github.com/echoares-lab/ai-gateway/issues/377))

Hardened docs/CI truth (Gate B in-memory / Gate C opt-in), config safety, request-path
modularization (`proxy_router` / `admin_routes`), and observability polish. Do not
reopen closed security epics (#305–#323) in place.


### Production cutover and durability

| Item | Status |
|------|--------|
| Observability epic [#351](https://github.com/echoares-lab/ai-gateway/issues/351) (#354–#356) | Closed |
| Cloudflare edge → k8s [#362](https://github.com/echoares-lab/ai-gateway/issues/362) | Closed |
| Gate D smokes k8s [#363](https://github.com/echoares-lab/ai-gateway/issues/363) | Closed |
| arc-dind storage-fast PVC [#358](https://github.com/echoares-lab/ai-gateway/issues/358) | Closed |
| Velero CH/MinIO schedules [#360](https://github.com/echoares-lab/ai-gateway/issues/360) | Closed (verify first successful backup) |
| Image pins + promote automation [#361](https://github.com/echoares-lab/ai-gateway/issues/361) | Closed |
| Durability epic [#352](https://github.com/echoares-lab/ai-gateway/issues/352) | Closed |
| PROD compose decommission + classic runner VMs [#364](https://github.com/echoares-lab/ai-gateway/issues/364) / [#353](https://github.com/echoares-lab/ai-gateway/issues/353) | Closed |

Local **dev** stacks (`./dev-env.sh` / `TESTING-*`) remain for development. Production is k8s only.

### Thin ops / credential intelligence

| Item | Status |
|------|--------|
| Quota status endpoint [#345](https://github.com/echoares-lab/ai-gateway/issues/345) / PR #349 | Closed |
| Quota unit tests [#348](https://github.com/echoares-lab/ai-gateway/issues/348) / PR #373 | Closed |

Broader credential-pool work remains candidate-only (C-CRED-*).

### Earlier roadmap themes (closed for documented scope)

Future work in these areas needs new atomic issues after promotion from
candidates — do not reopen these epics in place.

- **Local MCP hosting and tool gateway** ([#29](https://github.com/echoares-lab/ai-gateway/issues/29))
- **Adaptive provider intelligence** ([#31](https://github.com/echoares-lab/ai-gateway/issues/31)) — design/telemetry; runtime in candidates (C-RT-1)
- **Unified admin console** ([#32](https://github.com/echoares-lab/ai-gateway/issues/32)) — tenant panel parked via #109
- **First-class client compatibility** ([#36](https://github.com/echoares-lab/ai-gateway/issues/36))
- **Evaluation-driven routing quality loop** ([#37](https://github.com/echoares-lab/ai-gateway/issues/37)) — design done; runtime in candidates (C-RT-2)
- **Credential pool orchestration** ([#33](https://github.com/echoares-lab/ai-gateway/issues/33)) — candidates C-CRED-*
- **Environment promotion / config channels** ([#35](https://github.com/echoares-lab/ai-gateway/issues/35)) — candidates C-MDL-2
- Security-hardening / modularization tracks (#305, #309, #313, #317, #320) and
  mock-integration in-memory refactor (#336)

---

## Related docs

- [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) — unapproved inventory
- [CREDENTIAL_HEALTH.md](./CREDENTIAL_HEALTH.md)
- [CICD_PHASE2_CD_K3S.md](./CICD_PHASE2_CD_K3S.md)
- [CICD_PHASE2_STAGING.md](./CICD_PHASE2_STAGING.md)
- [issues/archive/post-audit-backlog-2026-06-13.md](../issues/archive/post-audit-backlog-2026-06-13.md)
- [Repo Improvement Workflow](process/REPO_IMPROVEMENT_WORKFLOW.md)
