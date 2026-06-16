# Roadmap Status

This page records roadmap coordination decisions that should be visible in the
repo, not only in GitHub issue comments. Implementation work still follows
`REPO_IMPROVEMENT_WORKFLOW.md`: agents may only claim approved, unassigned,
atomic issues and should not implement parent epics directly.

---

## Active roadmap areas

The current active roadmap focus is:

- **Local MCP hosting and tool gateway** ([#29](https://github.com/echoares-lab/ai-gateway/issues/29)):
  LiteLLM-centered MCP control plane, local MCP services, and safe operator
  workflow.
- **Adaptive provider intelligence** ([#31](https://github.com/echoares-lab/ai-gateway/issues/31)):
  provider health, latency, error, and fallback signals for adaptive routing.

Agents should only claim approved child issues. Do not claim parent epics
directly.

---

## Completed roadmap areas

These parent epics are closed for their current documented scope. Future work in
the same area should be opened as new atomic issues with fresh acceptance
criteria.

- **Unified admin console** ([#32](https://github.com/echoares-lab/ai-gateway/issues/32)):
  read-only status aggregator, dashboard, routing/fallback events, and the data
  contract are complete for the first implementation wave. Tenant/team panels
  remain deferred.
- **First-class client compatibility and integration profiles** ([#36](https://github.com/echoares-lab/ai-gateway/issues/36)):
  supported-client matrix, integration profiles, contract-test gaps, and
  per-client config snippets are complete.
- **Evaluation-driven routing quality loop** ([#37](https://github.com/echoares-lab/ai-gateway/issues/37)):
  design scope is complete in [EVAL_DRIVEN_ROUTING.md](./EVAL_DRIVEN_ROUTING.md).
  Runtime quality-routing work is deferred until explicitly reopened through
  child issues.

---

## Deferred tenant and onboarding areas

Tenant-related work is intentionally deferred as of 2026-06-16. These issues may
remain open as coordination anchors, but they should not be treated as
ready-to-claim implementation work until the roadmap is refreshed and child
issues are approved.

- **Multi-tenant workspace management** ([#30](https://github.com/echoares-lab/ai-gateway/issues/30)):
  foundational pieces already exist on `main`: tenancy model docs, `ak-*`
  metadata extraction, tenant-aware bootstrap helpers, and budget/rate-limit
  foundations. Remaining work should be narrowed before implementation, likely
  around runtime MCP visibility, admin visibility, and tenant lifecycle gaps.
- **Self-service onboarding for repos, apps, and AI clients** ([#34](https://github.com/echoares-lab/ai-gateway/issues/34)):
  tenant registration and client/bootstrap helpers exist, but the broader
  self-service flow needs a refreshed design before new implementation work.
- **Admin tenant/team panel** ([#109](https://github.com/echoares-lab/ai-gateway/issues/109)):
  keep deferred until tenant/workspace work is active again and the admin data
  contract is refreshed.

---

## Deferred platform-control areas

The following platform-control epics are intentionally deferred and should not be
treated as active next-priority work:

- **Credential pool orchestration and account health automation** ([#33](https://github.com/echoares-lab/ai-gateway/issues/33)).
- **Environment promotion and config release channels** ([#35](https://github.com/echoares-lab/ai-gateway/issues/35)).
- **RBAC and identity integration**.
- **Budgeting, quota governance, and chargeback**.
- **Policy engine for model, tool, and request controls**.

They are deferred because current work should focus first on MCP/local tool
hosting and the accepted active roadmap items above. Starting these areas before
the tenancy and control-plane foundations are settled would create premature
contracts around identity, ownership, enforcement, and billing semantics.

When revisited, each deferred area should be opened as a formal roadmap epic with
clear dependencies on the tenancy model, admin/control-plane decisions, and any
operator workflow needed to enforce the feature safely. Do not implement any of
these areas from this note alone; create approved child issues with acceptance
criteria before execution.

---

## Post-audit hardening and deferred backlog (2026-06-13)

See [issues/post-audit-backlog-2026-06-13.md](../issues/post-audit-backlog-2026-06-13.md) and GitHub epics #305, #309, #313, #317, #320.

---

## Related docs

- [Architecture Decision Record - MCP Control Plane Hosting](./ARCHITECTURE.md)
- [Adaptive Provider Routing - Design & Telemetry Plan](./ADAPTIVE_ROUTING.md)
- [Repo Improvement Workflow](../REPO_IMPROVEMENT_WORKFLOW.md)
