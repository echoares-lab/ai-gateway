# MCP Tool Visibility — Design Stub

> **Status:** Phase 5b runtime resolver in policy-engine (`allowed_mcp_servers` /
> `denied_mcp_servers` on `RoutingDecision`). LiteLLM tool-list filter (5c) pending.
> Implements the Phase 5
> optional scope for Epic #38 issue 38-20 ([#139](https://github.com/echoares-lab/ai-gateway/issues/139)),
> child of tenancy epic [#30](https://github.com/echoares-lab/ai-gateway/issues/30)
> follow-up **TENANCY-4** (workspace-level MCP tool visibility filters).
> Builds on [TENANCY.md](./TENANCY.md) §4.3 and [ARCHITECTURE.md](./ARCHITECTURE.md)
> (LiteLLM as MCP control plane).

---

## 1. Problem

MCP servers are registered **globally** in `litellm-config.yaml` under
`litellm_settings.mcp_servers`. Every client that receives tool definitions from
LiteLLM currently sees the same MCP catalog regardless of organization,
workspace, team, or repository.

[TENANCY.md](./TENANCY.md) requires workspace-level isolation: teams must not
discover or invoke MCP tools outside their approved scope (e.g. production repos
must not expose `mcp-postgres` write paths or cross-workspace filesystem roots).

Today there is no policy-engine hook or profile field that filters which MCP
server aliases are visible per `RoutingContext`.

---

## 2. Goal

Expose **only approved MCP tools** to each tenant slice by resolving
`policy_profiles.policy_json.mcp` at request time and filtering LiteLLM's tool
list before it reaches the client.

Non-goals for this stub:

- Moving MCP registration out of LiteLLM (ADR: LiteLLM remains control plane).
- Adding MCP routing logic to `translator.py` (ADR: pass-through only).
- Per-tool argument-level ACL (server-alias granularity first).
- Dynamic MCP server provisioning (static registry + profile filters).

---

## 3. Tenancy dimensions

Visibility resolves through the same hierarchy as routing policies
(`PolicyProfile.scope` / `scope_id`):

| Scope | Typical `scope_id` | MCP policy role |
|-------|-------------------|-----------------|
| `org` | `echoares` | Baseline deny/allow list for all workspaces |
| `workspace` | `echoares-core-ai` | Department tool bundles (e.g. search-only) |
| `team` | `echoares-core-eng` | Credential-pool-aligned tool sets |
| `repo` | `ai-gateway` | Repo-specific overrides (e.g. `mcp-git` only) |

Merge order: **repo → team → workspace → org** (most specific wins), consistent
with budget and rate-limit profile resolution in the policy-engine.

Tenant metadata from `ak-{org}-{workspace}-{team}-{repo}-{environment}` keys
(TENANCY.md §2.2) populates `RoutingContext` for lookup.

---

## 4. Policy schema sketch

```yaml
# policy_profiles.policy_json.mcp (illustrative)
mcp:
  mode: allowlist          # allowlist | denylist (default: denylist with empty list = allow all)
  servers:
    - mcp-brave
    - mcp-tavily
    - mcp-fetch
  # Optional per-server constraints (phase 2)
  server_options:
    mcp-postgres:
      read_only: true
      allowed_schemas: ["litellm", "public"]
```

| Field | Purpose |
|-------|---------|
| `mode` | `allowlist` exposes only named servers; `denylist` hides named servers |
| `servers` | LiteLLM `mcp_servers` alias names (e.g. `mcp-brave`) |
| `server_options` | Future: postgres schema allowlists, filesystem root caps |

Empty `policy_json.mcp` → **inherit parent scope**; if no profile in chain defines
MCP rules → **allow all registered servers** (backward compatible).

---

## 5. Runtime placement

```text
Client request (Bearer ak-…)
  → translator (tenancy metadata → RoutingContext)
  → LiteLLM chat completion with tools
       ↑
  policy-engine GET /v1/profiles/... (existing)
  NEW: MCP visibility resolver (38-20 phase 1b)
       → allowed_mcp_aliases: set[str]
  LiteLLM tool list filter (phase 1c)
       → strip disallowed MCP tool definitions before response
```

Per ADR, filtering happens **inside or immediately after LiteLLM's MCP tool
materialization**, not in the translator. Options (pick in implementation PR):

1. **LiteLLM virtual-key metadata** — attach `allowed_mcp_servers` to the key;
   LiteLLM filters if supported in target version.
2. **Translator post-filter** — only strips MCP-origin tools from `/v1/models` or
   tool-bearing responses; minimal, but touches translator (prefer option 1).
3. **Dedicated sidecar** — overkill for phase 1.

Audit: log filtered server aliases in `routing_decisions_log.rules_applied` when
a deny occurs (extends 38-16).

---

## 6. Phased implementation

| Phase | Issue slice | Deliverable |
|-------|-------------|-------------|
| **5a** (this stub) | 38-20 | Design doc + `policy_json.mcp` schema + dispatch |
| **5b** | 38-20 | Profile store reads `mcp` section; unit tests (**done**) |
| **5c** | follow-up | Wire resolver into LiteLLM tool exposure path |
| **5d** | follow-up | Admin console panel: effective MCP visibility per repo |
| **5e** | TENANCY-4 closeout | ROADMAP #30 child issue done; RUNBOOK operator guide |

**Dependencies:** 38-05 repo affinity profiles (done), tenant metadata in
translator ([#79](https://github.com/echoares-lab/ai-gateway/pull/79)), global
`mcp_servers` registry in `litellm-config.yaml`.

**Blocked by:** none for design; runtime **5c** benefits from 38-04 translator
wire but MCP filter can prototype on policy-engine + mock integration first.

---

## 7. Acceptance criteria (38-20)

- [x] Workspace/team/repo MCP visibility model documented
- [x] `policy_json.mcp` schema sketched with allowlist/denylist modes
- [x] Runtime placement options documented (LiteLLM-centric)
- [x] Phased implementation breakdown (5a–5e)
- [ ] Effective tool list filtered per tenant (runtime — follow-up 5c)
- [ ] Denied MCP access auditable in routing decision log (follow-up)

---

## 8. References

- [TENANCY.md](./TENANCY.md) — §4.3 MCP Tool Access, §5 child issue TENANCY-4
- [ARCHITECTURE.md](./ARCHITECTURE.md) — LiteLLM MCP control plane ADR
- [RUNBOOK.md](../RUNBOOK.md) — MCP server registration
- `issues/policy-engine-38-20-mcp-visibility.md` — issue tracker
