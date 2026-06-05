---
work_type: type:docs
summary: MCP tool visibility per workspace — policy profile filters for LiteLLM MCP servers (TENANCY-4).
problem: |
  MCP servers are globally registered; all clients see the same tool catalog.
  Tenancy requires workspace/team/repo-scoped MCP visibility without leaking tools.
why_now: |
  Phase 5 optional. TENANCY.md child #4 and Epic #30 depend on a concrete filter model;
  policy profiles (38-5) and LiteLLM mcp_servers registry are in place.
scope: |
  - Design doc: docs/MCP_TOOL_VISIBILITY.md
  - policy_json.mcp schema (allowlist/denylist, server aliases)
  - Runtime placement options (LiteLLM-centric per ADR)
  - Phased implementation breakdown (5b–5e)
  - TENANCY.md cross-link for child issue #4
non_goals:
  - Runtime tool filtering (follow-up 5c)
  - MCP routing in translator.py
  - Per-argument tool ACL
acceptance:
  - [x] Workspace-level MCP visibility model documented
  - [x] policy_json.mcp schema sketched
  - [x] Integration point with policy profiles identified
  - [x] Phased implementation issues outlined
tests: |
  N/A — design stub only (Gate A docs lint if wired in CI)
risks: |
  LiteLLM version may lack native per-key MCP filtering — fallback post-filter path needed.
dependencies:
  - docs/TENANCY.md
  - docs/ARCHITECTURE.md
files:
  - docs/MCP_TOOL_VISIBILITY.md
  - issues/policy-engine-38-20-mcp-visibility.md
  - docs/TENANCY.md
claim_status: in-review
blocks: []
blocked_by: []
execution_notes: |
  Design stub acceptable per Phase 5 dispatch. Runtime filter deferred until
  LiteLLM integration spike (5c).
github_issue: #139
---

# 38-20 — MCP Tool Visibility (Optional)

**Epic:** [#38](https://github.com/echoares-lab/ai-gateway/issues/38)  
**Tenancy parent:** [#30](https://github.com/echoares-lab/ai-gateway/issues/30) (TENANCY-4)  
**Design:** [docs/MCP_TOOL_VISIBILITY.md](../docs/MCP_TOOL_VISIBILITY.md)

## Claim

- **Claim-ID:** cursor-mcp-visibility-20260605T060000Z
- **Branch:** `feat/mcp-visibility`
- **Worktree:** `/home/dev/.cursor/worktrees/ai-gateway__SSH__dev_/575k`
- **Scope:** Design/docs stub — workspace-level MCP server visibility via policy profiles

**PR:** https://github.com/echoares-lab/ai-gateway/pull/148
