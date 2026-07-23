# Roadmap Status

Approved coordination decisions for what agents may claim. Implementation still
follows `docs/process/REPO_IMPROVEMENT_WORKFLOW.md`: claim approved, unassigned, atomic
issues only — never parent epics, and never items that exist only in
[FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md).

| Doc | Role |
|-----|------|
| **This file** | Approved Now / Next / Parked / Completed |
| [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) | Ideas **not** approved — document only until promoted here |

Last reviewed: 2026-07-17 (CLIProxy upstream-patch and dependency-update epic #413 approved under Next).

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


### Cross-Model Tool-Use & Protocol Benchmark

Approve coordination epic [#420](https://github.com/echoares-lab/ai-gateway/issues/420) and its three atomic children. This work introduces protocol-level checks for Claude/Cursor, a dev-only model-forcing escape hatch, and a headless benchmark harness evaluating cross-model tool-use fidelity.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Model-forcing escape hatch #421](https://github.com/echoares-lab/ai-gateway/issues/421) | `ai-gateway` | Ready; no dependency |
| 2 | [Protocol-level contract tests #422](https://github.com/echoares-lab/ai-gateway/issues/422) | `ai-gateway` | Depends on #421 |
| 3 | [Cross-model tool-use eval harness #423](https://github.com/echoares-lab/ai-gateway/issues/423) | `ai-gateway` | Depends on #421 and #422 |

Release invariants:
- Parent epic #420 is coordination-only;
- Model-forcing escape hatch must only be active in dev/test stacks (`ALLOW_DEV_MODEL_FORCE=true`);
- Do not check in mock credentials or real API keys for benchmark runs.

Plan: [`docs/superpowers/plans/cross-model-tool-use-benchmark.md`](./superpowers/plans/cross-model-tool-use-benchmark.md).


---

## Next — CI/CD failure alerting and honest Gate D signaling

Approve coordination epic [#468](https://github.com/echoares-lab/ai-gateway/issues/468)
and its four atomic children. Adds failure notification to the two
previously-silent pipelines that caused this session's staging-drift and
dormant-CLIProxyAPI-sync incidents, and fixes Gate D's misleading
naming/timing/masking.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Notify on promote-k3s-images.yml failure #470](https://github.com/echoares-lab/ai-gateway/issues/470) | `ai-gateway` | Ready; blocked on webhook secret provisioning |
| 1 | [Notify on weekly-upstream-track.yml failure #24](https://github.com/echoares-lab/CLIProxyAPI/issues/24) | `CLIProxyAPI` | Ready; blocked on webhook secret provisioning |
| 2 | [Fix Gate D naming/timing/masking #471](https://github.com/echoares-lab/ai-gateway/issues/471) | `ai-gateway` | Depends on Order-1 ai-gateway child |
| 3 | [Real post-promotion Gate D #102](https://github.com/echoares-lab/k3s-01/issues/102) | `k3s-01` | Depends on Order-2 |

Release invariants:
- parent epic is coordination-only;
- Order-1 ai-gateway child hard-blocks the litellm/langfuse-automation
  epic's Order-1 child (same file: `promote-k3s-images.yml`);
- Order-1 CLIProxyAPI child hard-blocks the CLIProxyAPI-unblock epic's PAT
  child (same file: `weekly-upstream-track.yml`);
- neither webhook secret exists yet — wiring may merge ahead of the secret
  being provisioned; closeouts must say so explicitly.

---

## Next — ArgoCD GitHub webhook for near-real-time sync

Approve coordination epic [#100](https://github.com/echoares-lab/k3s-01/issues/100)
and its two atomic children. Replaces ArgoCD's 120s poll interval with
near-instant webhook-triggered sync.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Register GitHub webhook #103](https://github.com/echoares-lab/k3s-01/issues/103) | `k3s-01` | Ready; may need repo-admin scope beyond agent auth |
| 2 | [Document webhook in runbook #104](https://github.com/echoares-lab/k3s-01/issues/104) | `k3s-01` | Depends on Order-1 |

Release invariants:
- parent epic is coordination-only;
- acceptance is evidence-based (observed sync latency), not just "PR
  merged" — most of this epic's work has no corresponding git diff.

---

## Next — Automate litellm/langfuse staging-to-production promotion

Approve coordination epic [#469](https://github.com/echoares-lab/ai-gateway/issues/469)
and its two atomic children. Extends the proven `bump-staging`/`promote`
pattern (currently app-images-only) to litellm and langfuse.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Mirror litellm/langfuse pins to k3s-01 staging #472](https://github.com/echoares-lab/ai-gateway/issues/472) | `ai-gateway` + `k3s-01` | Blocked on #468's Order-1 ai-gateway child (same file) |
| 2 | [Open k3s-01 prod PRs for litellm/langfuse #473](https://github.com/echoares-lab/ai-gateway/issues/473) | `ai-gateway` + `k3s-01` | Depends on Order-1 |

Release invariants:
- parent epic is coordination-only;
- never auto-merge the resulting prod PRs;
- litellm promotion must always restate the Prisma-migration-review gate
  from `docs/ops/DEPENDENCY_UPDATES.md` §LiteLLM, not treat it like the
  simpler app-image path.

---

## Next — CLIProxyAPI weekly upstream-sync automation unblock

Approve coordination epic [#23](https://github.com/echoares-lab/CLIProxyAPI/issues/23)
and its two atomic children. Unblocks the weekly fork-sync workflow's PR
creation and its dispatch into ai-gateway's promote pipeline.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [PAT secrets for PR creation + dispatch #25](https://github.com/echoares-lab/CLIProxyAPI/issues/25) | `CLIProxyAPI` | Blocked on #468's Order-1 CLIProxyAPI child (same file); also blocked on human-provisioned PAT values |
| 1 | [pr-path-guard exception for automation branches #26](https://github.com/echoares-lab/CLIProxyAPI/issues/26) | `CLIProxyAPI` | Ready; different file, parallel with the above |

Release invariants:
- parent epic is coordination-only;
- PAT secrets are a hard external/human dependency — closeout must state
  explicitly whether they were actually provisioned, not just wired.

---

## Next — Standardize k3s-01 image-pin mechanism

Approve coordination epic [#101](https://github.com/echoares-lab/k3s-01/issues/101)
and its two atomic children. Lowest priority in this plan — pure pin-hygiene
cleanup, no functional bug.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Audit pin mechanisms #105](https://github.com/echoares-lab/k3s-01/issues/105) | `k3s-01` | Ready |
| 2 | [Migrate holdouts to consistent mechanism #106](https://github.com/echoares-lab/k3s-01/issues/106) | `k3s-01` | Depends on Order-1; soft-depends on Epic 3 landing first |

---

## Next — CLIProxy upstream patch and dependency update loop

Approve coordination epic
[#413](https://github.com/echoares-lab/ai-gateway/issues/413) and its atomic
children. The work resets the CLIProxyAPI fork onto current upstream with only
the quota contract carried as local patches, makes cliproxy promotion pass the
existing staging deep-smoke gate, and establishes a risk-tiered dependency
update and rollback loop.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 0 | [ROADMAP + design/plan #414](https://github.com/echoares-lab/ai-gateway/issues/414) | `ai-gateway` | Ready; no dependency |
| 1 | [Reset fork onto upstream #12](https://github.com/echoares-lab/CLIProxyAPI/issues/12) | `CLIProxyAPI` | Blocked on #414; drop auth-hardening and batch patches |
| 2 | [Re-port quota foundation and live contract #13](https://github.com/echoares-lab/CLIProxyAPI/issues/13) | `CLIProxyAPI` | Depends on CLIProxyAPI #12; replaces closed #6 and #5 |
| 3 | [Weekly upstream track + Nexus candidate #11](https://github.com/echoares-lab/CLIProxyAPI/issues/11) | `CLIProxyAPI` | Depends on CLIProxyAPI #12 and #13 |
| 3 | [Include cliproxy in promote gate #415](https://github.com/echoares-lab/ai-gateway/issues/415) | `ai-gateway` | Depends on #414; soft dependency on CLIProxyAPI #11 |
| 4 | [Dependency inventory + Renovate policy #416](https://github.com/echoares-lab/ai-gateway/issues/416) | `ai-gateway` | Depends on #414 |
| 4 | [Per-component gates and rollback playbook #417](https://github.com/echoares-lab/ai-gateway/issues/417) | `ai-gateway` | Depends on #414 and #416; soft dependency on #415 |
| 5 | [Staging-to-production cliproxy cutover #418](https://github.com/echoares-lab/ai-gateway/issues/418) | `ai-gateway` + `k3s-01` | Depends on CLIProxyAPI #13 and #414; #415 preferred |
| 6 | [Archive Management-Center and prune fork branches #419](https://github.com/echoares-lab/ai-gateway/issues/419) | ops | Depends on #418 |

Release invariants:

- parent epic #413 is coordination-only; claim one atomic child per agent,
  branch, external worktree, and isolated slot where a live stack is required;
- retain no more than two documented quota commits above upstream; do not carry
  overlapping auth-hardening or unused batch-credential patches;
- a candidate cliproxy Nexus SHA must pass staging deep-smoke `--full`,
  including quota assertions, before its exact digest is pinned in production;
- high-risk dependency updates never auto-merge and require staging evidence;
- production uses immutable digests, while the immediately previous digest and
  any migration or credential restore procedure remain recorded for rollback;
- one staging cliproxy rollback drill is recorded in the epic closeout; and
- closed CLIProxyAPI #5 and #6 are historical inputs only and must not be
  reclaimed.

Spec: [`docs/superpowers/specs/2026-07-17-cliproxy-upstream-patch-dep-updates-design.md`](./superpowers/specs/2026-07-17-cliproxy-upstream-patch-dep-updates-design.md).
Plan: [`docs/superpowers/plans/2026-07-17-cliproxy-upstream-patch-dep-updates.md`](./superpowers/plans/2026-07-17-cliproxy-upstream-patch-dep-updates.md).

---

## Next — Staging deep-smoke promote gate

Coordination epic
[#396](https://github.com/echoares-lab/ai-gateway/issues/396) and children are
**done**. Staging `--full` deep-smoke is the CI-enforced promote gate before
pinning digests to production (API shapes, streaming, OpenAPI-hardened quota,
cluster readiness, `LiteLLM_SpendLogs`).

| Order | Atomic issue | State |
|------:|--------------|-------|
| 0 | [ROADMAP + design/plan #397](https://github.com/echoares-lab/ai-gateway/issues/397) | Done |
| 1 | [`--quick` scaffold #398](https://github.com/echoares-lab/ai-gateway/issues/398) | Done |
| 2 | [`--full` HTTP shapes #399](https://github.com/echoares-lab/ai-gateway/issues/399) | Done |
| 2 | [Soft admin + quota #400](https://github.com/echoares-lab/ai-gateway/issues/400) | Done (superseded by #403) |
| 3 | [SpendLogs + cluster #401](https://github.com/echoares-lab/ai-gateway/issues/401) | Done |
| 3 | [Promote checklist docs #402](https://github.com/echoares-lab/ai-gateway/issues/402) | Done |
| 4 | [CI gate promote on deep-smoke #410](https://github.com/echoares-lab/ai-gateway/issues/410) | Done |
| 5 | [Harden quota asserts #403](https://github.com/echoares-lab/ai-gateway/issues/403) | Done |

Invariants:

- do **not** replace advisory `production-health-heartbeat.yml`;
- default `--env staging`; prod `--quick` is optional/incident-only;
- serialize `scripts/ops/deep-smoke.*`;
- `/admin/quota/status` asserts match OpenAPI (`docs/openapi/gateway-engine.yaml`).

Spec: [`docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md`](./superpowers/specs/2026-07-17-staging-deep-smoke-design.md).  
Plan: [`docs/superpowers/plans/2026-07-17-staging-deep-smoke.md`](./superpowers/plans/2026-07-17-staging-deep-smoke.md).

---

## Next — Model Metadata Expansion and Reasoning Normalization

Approve epic [#486](https://github.com/echoares-lab/ai-gateway/issues/486) and its atomic children (promoted from candidates `C-MDL-3` and `C-RT-6`). This work expands model metadata in `config/model-registry.yaml` and `ModelRegistryRecord` with `supports_reasoning` and `context_window` fields, normalizes reasoning parameters and thinking blocks across providers, and updates token usage reporting.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Model metadata capability expansion #487](https://github.com/echoares-lab/ai-gateway/issues/487) | `ai-gateway` | Ready; no dependency |
| 2 | [Reasoning token and parameter normalization #488](https://github.com/echoares-lab/ai-gateway/issues/488) | `ai-gateway` | Depends on #487 |

Release invariants:
- Parent epic #486 is coordination-only;
- Model capabilities (`supports_reasoning`, `context_window`) must default gracefully when unspecified;
- Do not break backward compatibility with existing LiteLLM or Postgres schema contracts.

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


### Policy Engine and Routing Refactor ([#38](https://github.com/echoares-lab/ai-gateway/issues/38))

Fully implemented as an **in-process** system under `services/gateway-engine/core/policy/` (instead of a standalone service), providing fast in-memory evaluation for:
- Repository and agent affinity
- Budget gates and Redis-backed rate limits
- Fallback ordering and MCP visibility filters


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
