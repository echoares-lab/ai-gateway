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
- **Multi-tenant workspace management** ([#30](https://github.com/echoares-lab/ai-gateway/issues/30)):
  tenancy model and workspace-level configuration foundations.
- **Adaptive provider intelligence** ([#31](https://github.com/echoares-lab/ai-gateway/issues/31)):
  provider health, latency, error, and fallback signals for adaptive routing.
- **Unified admin console** ([#32](https://github.com/echoares-lab/ai-gateway/issues/32)):
  operational visibility and control-plane UI once the underlying models are
  stable.

Medium-priority roadmap epics remain available for future child issues:

- **Credential pool orchestration and account health automation** ([#33](https://github.com/echoares-lab/ai-gateway/issues/33)).
- **Self-service onboarding for repos, apps, and AI clients** ([#34](https://github.com/echoares-lab/ai-gateway/issues/34)).
- **Environment promotion and config release channels** ([#35](https://github.com/echoares-lab/ai-gateway/issues/35)).
- **First-class client compatibility and integration profiles** ([#36](https://github.com/echoares-lab/ai-gateway/issues/36)).

Low-priority roadmap epics are coordination items until split into approved
atomic issues:

- **Evaluation-driven routing quality loop** ([#37](https://github.com/echoares-lab/ai-gateway/issues/37)).

---

## Deferred platform-control areas

The following platform-control epics are intentionally deferred and should not be
treated as active next-priority work:

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

## Related docs

- [Architecture Decision Record - MCP Control Plane Hosting](./ARCHITECTURE.md)
- [Adaptive Provider Routing - Design & Telemetry Plan](./ADAPTIVE_ROUTING.md)
- [Repo Improvement Workflow](../REPO_IMPROVEMENT_WORKFLOW.md)
