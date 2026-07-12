# Roadmap Status

Approved coordination decisions for what agents may claim. Implementation still
follows `docs/process/REPO_IMPROVEMENT_WORKFLOW.md`: claim approved, unassigned, atomic
issues only — never parent epics, and never items that exist only in
[FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md).

| Doc | Role |
|-----|------|
| **This file** | Approved Now / Next / Parked / Completed |
| [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) | Ideas **not** approved — document only until promoted here |

Last reviewed: 2026-07-12 (Stability Foundation completed via #377).

---

## Now

*No active Now track.* Parked tenancy anchors remain blocked pending a multi-tenant
decision (see Parked). To start product work: promote an item from
[FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) into this file and open atomic
GitHub issues with `status:ready`.

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
