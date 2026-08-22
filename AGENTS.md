<!-- BEGIN GENERATED — dev-policies/tooling/scripts/render-agents-md.py. Do not edit by hand. -->

# Agent Directives — `ai-gateway`

> **Generated from the Obsidian vault. Do not edit this region by hand** — run `dev-policies/tooling/scripts/render-agents-md.py --repo . --profile multi-service-stack`. Edits here are overwritten and CI fails on drift.

**Operative authority:** `/home/dev/obsidian-vault/02 Areas/Policies/Master-Policy.md` and its linked policy notes. On any conflict between this file and the vault, **the vault wins** — this file is a rendering of it, not a second source of truth.

**Repo profile:** `multi-service-stack`

## Context load order

1. This file.
2. `/home/dev/obsidian-vault/01 Projects/<Project>/Overview.md` — check its `## Policy Exceptions` section.
3. The specific vault policy, when you need detail beyond what is rendered here.

---

## Preserving Code Integrity & Documentation

*Source: `Master-Policy.md` — do not edit here.*

- **No Blanket Deletions:** Never delete existing docstrings, structural comments, or unit tests unless explicitly authorized by user intent.
- **Strict Conditional Scoping:** When modifying conditional logic or adding experimental features, ensure logic is strictly scoped and tested against all execution paths.
- **Maintain Public API Signatures:** Do not alter function signatures or parameter keys without searching and updating every invocation site in the codebase.

## Diagnostic Integrity & Log Analysis

*Source: `Master-Policy.md` — do not edit here.*

- **Empirical Diagnostics Only:** Never form a diagnostic hypothesis for a runtime failure without fetching and reading the un-truncated error log.
- **No Masking Symptoms:** Resolving errors by catching silent exceptions, swallowing errors, returning dummy fallback data, or commenting out failing assertions is **strictly forbidden**.

## Verification & Definition of Done

*Source: `Master-Policy.md` — do not edit here.*

- **Mandatory Runtime Verification:** Editing code is NOT completing the task. No task is resolved until build, test, or lint commands are executed and verified with `0` exit code.
- **Acknowledge Command Failures:** Never gloss over build timeouts or permission errors. Acknowledge and resolve every build issue explicitly.

## Mandatory MCP Tool Suite & Subagent Equipping Governance

*Source: `Master-Policy.md` — do not edit here.*

- **MCP servers are configured at USER scope, not per repository (resolved 2026-08-14).** The canonical server list lives once in `~/.claude.json`. Repositories MUST NOT carry a root `.mcp.json`; agents MUST NOT create one when scaffolding or cloning. Add servers with `claude mcp add -s user` (or `add-json -s user` when `env` blocks are involved).
  - **Why per-repo scaffolding was wrong:** MCP resolves from the session's **startup directory**, not from whatever files an agent later touches. Agents here routinely start in one repo and do work in others, so a `.mcp.json` in the repo being edited contributes nothing — it only ever applies when the session happened to start there. The per-repo mandate therefore did not deliver the guarantee it claimed; user scope delivers it unconditionally.
  - **This supersedes the `.mcp.json` / `.mcp.json.example` split of 2026-08-12.** That split existed solely because the working file carried a live `OBSIDIAN_API_KEY`. The `obsidian` server is now keyless (below), so there is no credential to keep out of git and no reason for either file to exist. Both are removed from every repository; the CI gate in CICD-Policy §1.1.1 is retired with them.
  - **Per-repo disabling is not achievable and MUST NOT be attempted.** `deniedMcpServers` has no effect outside managed/enterprise settings (verified empirically — the denied server still loads). `enabledMcpjsonServers` / `disabledMcpjsonServers` work only for servers declared in a project `.mcp.json`, which no longer exists. A user-scope server is on in every repository, by design.
  - **Credentials use `${VAR}` expansion, which works at user scope** (verified). Tokens MUST be referenced as `${VAR}` in `~/.claude.json` and supplied from the secret manager per §4.1 — never inlined.
- **Local Agent Memory (`memory`)**: `~/.claude.json` MUST define `@modelcontextprotocol/server-memory` writing to `/home/dev/.local/share/agent-memory/memory.json`. Agents MUST log facts, user preferences, and key architectural entities for sub-second retrieval across sessions.
- **Obsidian Vault Memory (`obsidian`)**: `~/.claude.json` MUST define the **keyless** `npx -y obsidian-mcp /home/dev/obsidian-vault` variant. The `obsidian-mcp-server` REST variant is **prohibited** — it requires `OBSIDIAN_API_KEY`, which is what drove that key into plaintext across 19 working trees. Agents MUST read/write specs, ADRs, and project documentation in `/home/dev/obsidian-vault/01 Projects/<Project>/`.
- **Documentation MCPs (`context7`, `cf-docs`)**: Agents MUST query `context7` for open-source library/framework specs and `cf-docs`/`cf-bindings` for Cloudflare platform specs before generating implementation code.
- **Database & Persistence MCPs (`postgres`)**: Agents MUST use the `postgres` MCP tools to inspect table schemas, indexes, constraints, and cache keys instead of writing manual debug scripts. The `redis` MCP server is **not provisioned** — it failed to start on every session and was removed 2026-08-14; use `redis-cli` until a working server is configured.
- **Infra & DevOps MCPs (`argocd`, `grafana`, `homarr`)**: Agents MUST use `argocd` and `grafana` MCP tools for deployment state and observability. The `kubernetes` and `docker` MCP servers are **not provisioned** — both failed to start on every session and were removed 2026-08-14; use `kubectl` and `docker` directly until working servers are configured.
- **Subagent MCP Equipping**: Subagents are spawned with the **`Agent` tool** (`subagent_type` selects the agent). There is no `invoke_subagent` call and no `enable_mcp_tools` flag — those are primitives of a different harness and were never executable here. User-scope MCP servers declared in `~/.claude.json` are reachable by every subagent automatically; schemas for deferred tools load on demand via `ToolSearch`. The real control is the agent definition: where a subagent type is defined in `.claude/agents/*.md`, its `tools:` frontmatter MUST retain the `mcp__<server>__<tool>` entries its task needs, because omitting them is what actually withdraws MCP access.

#### 1.5.1 Memory Tiering & Retrieval Protocol
- **Tier 1 (Fast Operational Memory - `memory`)**: Use `@modelcontextprotocol/server-memory` (JSON Knowledge Graph) for user preferences, tech stack choices, active sprint goals, entity relationships, and sub-second key-value lookups.
- **Tier 2 (Persistent Vault Documentation - `obsidian`)**: Use Obsidian Markdown notes for long-term project specs, ADRs (`0001-title.md`), Runbooks, API contract specs, and post-mortems.

## Repository Documentation Minimalism

*Source: `Master-Policy.md` — summary; the full section is in the vault. Do not edit here.*

- **Rule:** project documentation — epics, backlogs, ADRs, specs, architecture, runbooks, research reports, design/implementation plans, status notes — lives **exclusively** in `/home/dev/obsidian-vault/01 Projects/<Project>/`, never in a code repository. When removing documentation from a repo, **move** it to the vault; never delete.
- **Permitted markdown in a repo (exhaustive):** `README.md` (orientation + vault pointer), `AGENTS.md` (`CLAUDE.md` is an untracked pointer to it), `CHANGELOG.md` / `LICENSE` / `CONTRIBUTING.md` / `SECURITY.md`, format notes adjacent to the artifacts they describe, `.github/` files GitHub consumes, and code-/CI-consumed markdown with a live consumer (`docs/runbooks/`, `docs/openapi/`). Vendored upstream forks are exempt.
- **Enforced mechanically, not by memory:** a `PreToolUse` hook (`.claude/settings.json` in every repo, `block-prohibited-docs.py`) denies the write and names the vault destination; `pre-commit` (`doc-minimalism` + the shrink-only baseline ratchet) and the `policy-check` CI gate catch anything that gets past it.
- **Full text and placement rules:** Master-Policy §1.6 in the vault, or the `policy-doc-placement` skill.

## Modern Toolchain & Language Guidelines

*Source: `Coding-Standards-Policy.md` — do not edit here.*

### 2.1 Python (Modern Toolchain Mandate: `uv` & `ruff`)
- **Runtime Target:** Python 3.12+.
- **Mandatory Package & Environment Manager (`uv`):** Use **`uv`** (`uv pip`, `uv venv`, `uv sync`, `uv run`) for ultra-fast dependency resolution and virtual environment management. Traditional `pip` and `poetry` are deprecated.
- **Nexus PyPI Index Mandate:** All `uv` operations MUST target the local Nexus repository index at `https://nexus.infra.plexplease.com/repository/pypi-group/simple` via global `~/.config/uv/uv.toml` or repository-level `uv.toml`. *(Corrected 2026-08-12: this previously read `pypi-all`, which returns HTTP 404. Verified live — `pypi-group` returns 200.)*
- **Mandatory Formatter & Linter (`ruff`):** Use **`ruff check .`** and **`ruff format .`** for linting and code formatting.
- **Type Annotations:** Full type hinting (`typing` / Python 3.12 generic syntax).
- **Data Models:** Use Pydantic v2 for data parsing, schema validation, and config loading.
- **Database Access:** Async ORM or Repository pattern (`SQLAlchemy async` / `tortoise-orm`). Synchronous database calls in async routes are strictly prohibited.

### 2.2 TypeScript / Node.js (Modern Toolchain: `bun` & `biome`)
- **Runtime Target:** Node.js 22 LTS or **`bun`**.
- **Package Manager:** Prefer **`bun`** or `pnpm` for fast dependency resolution.
- **Imports & Modules:** ESM imports only (`import ... from '...'`). CommonJS `require()` is forbidden unless interfacing with legacy scripts.
- **Formatter & Linter:** **`Biome`** or ESLint configured with strict zero-warning enforcement.
- **State & Validation:** Use `Zod` or `TypeBox` for API payload and environment variable validation.
- **Async Pattern:** Standardize on `async`/`await` over chained raw promises or callback handlers.

### 2.3 Go (Golang)
- **Runtime Target:** Go 1.22+.
- **Formatter & Linter:** `gofmt -s` and `golangci-lint run`.
- **Project Structure:** Follow standard Go project layout (`cmd/`, `internal/`, `pkg/`).
- **Error Handling:** Check `if err != nil` explicitly. Never ignore returned errors (`_ = func()`).
- **Concurrency Safety:** Always pass `context.Context` as the first argument in long-running or network functions for timeout propagation.

---

## Test Time Caps

*Source: `Testing-Policy.md` — do not edit here.*

**This table is the only place test time caps are defined.** Master-Policy §2.1 and CICD-Policy §1.1 point here rather than restating a number — previously the same two numbers appeared with four different scopes across those documents.

| Tier | Scope of the cap | Cap |
|---|---|---|
| Tier 1 — Static analysis & lint | Whole repo | No separate cap; counts toward the CI gate total |
| Tier 2 — Unit | Whole repo, entire unit suite | **10 seconds** |
| Tier 3 — Integration | Per suite, inside the CI gate total | **45 seconds** |
| Tier 4 — E2E (mocked) | Own job, not part of the PR gate | **60 seconds** per suite |
| **CI gate total (Tiers 1–3)** | One PR run — the number CI actually enforces | **60 seconds** |

Notes:
- Tier 4 E2E runs against the `CLIProxyAPI` mock in its own job and is **excluded** from the Tiers 1–3 gate total.
- A suite exceeding its cap MUST be refactored or parallelized. Raising a cap requires a documented Policy Exception per Policy-Exceptions §2.

**Why 45s for Tier 3 (resolved 2026-08-13).** The superseded text set *both* "individual
test suite ≤ 60s" and "Tiers 1–3 combined ≤ 60s", which cannot both hold — if integration
alone may consume the full 60s, Tier 2's 10s already blows the combined budget. The combined
gate is authoritative because it is the figure CI enforces
(CICD-Policy §1.1), so Tier 3 gets the remainder:
60s total − 10s unit − ~5s lint ≈ **45s**. Do not reintroduce a second standalone 60s figure.

## Automated Quality Gates

*Source: `CICD-Policy.md` — do not edit here.*

Every Pull Request and commit MUST pass the following automated CI quality gates before code can be merged:
1. **MCP Scaffolding Gate — RETIRED 2026-08-14; guard relocated, clarified 2026-08-15.** MCP servers are configured once at user scope in `~/.claude.json`; repositories carry no `.mcp.json` or `.mcp.json.example`, so there is nothing in a checkout for CI to verify and the gate is removed from workflows. What retirement dropped is the requirement to **have** the file — it never licensed re-introducing one. The original instruction to "drop the `.mcp.json` checks from `scripts/setup_git_hooks.sh`" was accurate only about *where* the check lives: the guard moved rather than disappeared. It is now the `no-mcp-json` hook in each repo's `.pre-commit-config.yaml`, which fails any commit that stages `.mcp.json` or `.mcp.json.example`; `scripts/setup_git_hooks.sh` no longer writes hook bodies inline and only runs `pre-commit install` (reference implementation: `hardware`). A checkout whose hooks are not installed has no protection at all — running `pre-commit install` per clone and per worktree is what makes the ban real. Rationale — including why per-repo scaffolding never delivered its guarantee — is in Master-Policy §1.5.
2. **Static Analysis & Linting:** Code formatting and zero-warning lint checks (`ruff`, `biome`, `gofmt`).
3. **Security & Secret Scanning:** `gitleaks` over the checked-out tree, using a repo-local `.gitleaks.toml`, on every push and PR — **and in the Obsidian vault on the same footing**. Scope, allowlist discipline, and the sensitive-non-secret rules are defined in Secrets-Policy §7.
4. **Automated Test Matrix:** Execution of Unit and Integration test suites (Tiers 1–3). **Time caps are defined once in Testing-Policy §3.1** — do not restate a number here.
5. **Build Validation:** Compilation check of container images or binary packages.

## Authorized Artifact Repository

*Source: `CICD-Policy.md` — do not edit here.*

- **Mandatory Container Registry:** All container images across all projects MUST be published exclusively to the local **Nexus Registry**. Nexus exposes two Docker endpoints with different roles (clarified 2026-08-10 during the MLflow deployment):
  - **Push (hosted repo):** `nexus-docker.infra.plexplease.com` — the writable endpoint; all `docker push` operations target this host, and in-cluster deployment manifests reference it (with the `nexus-docker-pull` imagePullSecret).
  - **Pull-through (group repo):** `nexus-registry.infra.plexplease.com` — read-only aggregation over the hosted repo + upstream proxies. Pushing to a group endpoint is a Nexus PRO feature and is rejected on our OSS install ("Deploying to groups is a PRO-licensed feature").
- **Binary Packages & Helm Charts:** Staged exclusively in the local Nexus Repository (`https://nexus.infra.plexplease.com`).
- Use of external public registries (e.g. Docker Hub, GHCR) for finished project images is strictly prohibited without an explicit project policy exception.

## OpenBao Pathing & Metadata Standard

*Source: `Secrets-Policy.md` — do not edit here.*

### 2.1 KV-v2 Secret Path Taxonomy

All KV-v2 secret paths in OpenBao MUST follow this exact taxonomy:

`kv/data/agents/{agent_type}/{agent_id}/{environment}/`

- `agent_type` — `autonomous` (unattended workers, cron, K3s pods, CI/CD) or
  `interactive` (local coding agents, interactive CLI tools).
- `environment` — `prod`, `staging`, `homelab`, or `global` (environment-agnostic).

**The mount is `kv`, not `secret`.** The `data/` segment is an HTTP-API artifact: the same
secret is `kv/data/agents/…` over REST, `bao kv get kv/agents/…` on the CLI, and
`remoteRef.key: agents/…` with `path: kv` on the store.

`bao secrets list` returns four mounts and `secret/` is not among them, so every
`secret/data/agents/...` path this estate ever wrote was unresolvable as stated.

### 2.2 `_metadata` payload

Every secret payload carries a `_metadata` object alongside its credential keys.

```json
{
  "api_key": "[SECRET_VALUE]",
  "_metadata": {
    "owner": "team-or-handle",
    "repository": "https://github.com/org/repo-name",
    "allowed_agent_roles": ["k3s-01-external-secrets", "hardware-collector"],
    "class": "derived",
    "parent": "Cloudflare - Account API Token - Prod",
    "max_ttl_seconds": 3600,
    "migrated_from": "kv/data/prod/platform/cloudflare",
    "created_at": "2026-08-11T00:00:00Z"
  }
}
```

`class` is `native` (this estate is the issuer — internal CA, database roles, service
accounts it controls) or `derived` (minted from a core external credential held in
1Password). A `derived` secret also carries `parent`, naming the 1Password item it was
minted from.

Everything in OpenBao is internal to this estate, because core external credentials stay
in 1Password (§1). What differs is who can reissue the thing: a native credential this
estate rotates on its own, while rotating a derived one means going back to its parent, in
a vendor console, as a human. Without `parent` recorded, that trail has to be
reconstructed from memory during an incident.

**Use explicit `data[].property` selection, not `dataFrom: extract:`**, for any
ExternalSecret reading an agent-scoped path.

Because `_metadata` sits inside the payload, a consumer that reads the whole secret
receives it as a data key — observed widening `ai-gateway-secrets` from 29 keys to 30.

### 2.3 Writers merge, never replace

**Any writer that does not own every key at its path MUST use `bao kv patch` or a
read-modify-write.** `put` is permitted only where the writer owns the whole payload.

`bao kv put` and `POST /v1/kv/data/<path>` replace the entire payload — a writer that sets
a subset silently deletes the rest, `_metadata` included. Two scripts were caught
mid-migration about to do exactly this to paths holding 5 and 14 keys.

### 2.4 Compare key sets before repointing

Agent-scoped paths may be supersets of the legacy sources they replaced. Before repointing
any consumer, diff the **key sets**, not just the values, and select keys explicitly.

One consolidated destination holds 31 keys where its source had 4; a naive repoint would
have widened that namespace's Secret to 32 keys.

### 2.5 Generated credentials MUST be URL-safe

Generate machine credentials from the RFC 3986 unreserved set (`A-Z a-z 0-9 - . _ ~`) and
assert the result before storing it. Applies to `class: native` credentials, whose
alphabet this estate chooses. A `derived` credential takes whatever form the vendor
issues: store it verbatim and URL-encode at the point of use.

`openssl rand -base64` emits `+`, `/` and `=`, all reserved in a URI. A base64 password
authenticated fine natively and put Langfuse staging into CrashLoopBackOff only through
the URL its migration built — so the failure is invisible to any check that asks merely
whether the credential works.

```bash
case "$NEW" in *[+/=\&\#?%@\ ]*) echo "FATAL: unsafe char generated"; exit 1;; esac
```

---

## Commit

*Source: `Git-Policy.md` — do not edit here.*

### 2.1 Conventional Commits Specification
All commit messages MUST follow the **Conventional Commits** format in present imperative tense:

```
<type>(<scope>): <short description in present tense>

[optional body explaining rationale]
```

#### Allowed Types:
- **`feat`**: A new feature for the user or system.
- **`fix`**: A bug fix.
- **`refactor`**: Code change that neither fixes a bug nor adds a feature.
- **`docs`**: Documentation changes only.
- **`test`**: Adding missing tests or correcting existing tests.
- **`chore`**: Maintenance, build configs, or dependency updates.
- **`security`**: Security patches, secret scrubbing, or permission updates.

### 2.2 Agent Commit Identification & Co-Authorship
When an AI agent (AGY, Codex, Cursor, Claude) creates a commit, it MUST configure appropriate git identity and include co-authorship metadata:

```bash
git config user.name "AGY Agent"
git config user.email "agy-agent@users.noreply.github.com"
```

For collaborative edits between human and agent (or subagents):
```git
feat(ai-gateway): implement quota-aware routing logic

Co-authored-by: AGY Agent <agy-agent@users.noreply.github.com>
Co-authored-by: Reviewer Agent <reviewer@users.noreply.github.com>
```

---

---

## Provenance

| Policy | Version | Updated |
|---|---|---|
| `CICD-Policy.md` | 1.4 | 2026-08-16 |
| `Coding-Standards-Policy.md` | 1.1 | 2026-08-12 |
| `Git-Policy.md` | 1.0 | 2026-07-29 |
| `Master-Policy.md` | 2.2 | 2026-08-22 |
| `Secrets-Policy.md` | 4.0 | 2026-08-21 |
| `Testing-Policy.md` | 1.2 | 2026-08-13 |

<!-- END GENERATED — repo-specific directives may follow and are preserved. -->
