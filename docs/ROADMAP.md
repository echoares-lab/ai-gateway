# Roadmap Status

Approved coordination decisions for what agents may claim. Implementation still
follows `REPO_IMPROVEMENT_WORKFLOW.md`: claim approved, unassigned, atomic
issues only — never parent epics, and never items that exist only in
[FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md).

| Doc | Role |
|-----|------|
| **This file** | Approved Now / Next / Parked / Completed |
| [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) | Ideas **not** approved — document only until promoted here |

Last reviewed: 2026-07-11.

---

## Now — production cutover and durability

Finish making the k3s deployment the durable production path.

| Epic / issue | Role |
|--------------|------|
| [#352](https://github.com/echoares-lab/ai-gateway/issues/352) | Durability & GitOps hygiene (parent) |
| [#358](https://github.com/echoares-lab/ai-gateway/issues/358) | arc-dind runner cache → storage-fast PVC |
| [#360](https://github.com/echoares-lab/ai-gateway/issues/360) | Velero backups for ClickHouse + MinIO |
| [#361](https://github.com/echoares-lab/ai-gateway/issues/361) | Pin image tags + rollout automation |
| [#353](https://github.com/echoares-lab/ai-gateway/issues/353) | Production cutover & decommission (parent) |
| [#364](https://github.com/echoares-lab/ai-gateway/issues/364) | Decommission old compose host + classic runners |

Agents should only claim the open child issues above (or other approved children
of these epics). Do not claim parent epics directly.

---

## Next — thin ops / credential intelligence

After cutover/durability, the only approved capability track is a **thin** ops
wave:

| Issue | Role |
|-------|------|
| [#348](https://github.com/echoares-lab/ai-gateway/issues/348) | Unit tests for `GET /admin/quota/status` (parent epic [#345](https://github.com/echoares-lab/ai-gateway/issues/345)) |

Optional small polish of the merged quota/status admin surface is in scope only
if needed to make #348 meaningful. **Not** in this wave: credential pool
orchestration, multi-account load balancing, remediation automation, or
chargeback — those live in [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md)
(C-CRED-*).

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

## Completed (current and prior waves)

### Current wave

- **Observability — wire tracing + centralize data services**
  ([#351](https://github.com/echoares-lab/ai-gateway/issues/351)): children
  #354–#356 done; epic closed 2026-07-11.
- **OAuth quota status endpoint** ([#345](https://github.com/echoares-lab/ai-gateway/issues/345)):
  route shipped via PR #349; remains open only until #348 tests land.
- Cutover children already done: Cloudflare edge (#362), Gate D on k8s (#363),
  and durability children #357 / #359.

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
- [issues/post-audit-backlog-2026-06-13.md](../issues/post-audit-backlog-2026-06-13.md)
- [Repo Improvement Workflow](../REPO_IMPROVEMENT_WORKFLOW.md)
