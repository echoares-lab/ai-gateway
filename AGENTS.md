<!-- BEGIN GENERATED — homelab-policies/tooling/scripts/render-agents-md.py. Do not edit by hand. -->

# Agent Directives — `ai-gateway`

> **Generated from homelab-policies. Do not edit this region by hand** — run `homelab-policies/tooling/scripts/render-agents-md.py --repo . --profile multi-service-stack`. Edits here are overwritten and CI fails on drift.

**Operative authority:** `homelab-policies` repository (`policy/rules/*.yaml` and `docs/policies/Master-Policy.md`). On any conflict, **homelab-policies is the single source of truth**.

**Repo profile:** `multi-service-stack`

## Context load order

1. This file (`AGENTS.md`).
2. In-repo `docs/` or `homelab-policies/work/<project>.yaml` for project-specific architecture and active work.
3. The specific policy under `homelab-policies/docs/policies/`, when you need detail beyond what is rendered here.

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
  - **This supersedes the `.mcp.json` / `.mcp.json.example` split of 2026-08-12.** That split existed solely because the working file carried a live `OBSIDIAN_API_KEY`. The `obsidian` server is now keyless (below), so there is no credential to keep out of git and no reason for either file to exist. Both are removed from every repository; the CI gate in [CICD-Policy §1.1.1](CICD-Policy.md) is retired with them.
  - **Per-repo disabling is not achievable and MUST NOT be attempted.** `deniedMcpServers` has no effect outside managed/enterprise settings (verified empirically — the denied server still loads). `enabledMcpjsonServers` / `disabledMcpjsonServers` work only for servers declared in a project `.mcp.json`, which no longer exists. A user-scope server is on in every repository, by design.
  - **Credentials use `${VAR}` expansion, which works at user scope** (verified). Tokens MUST be referenced as `${VAR}` in `~/.claude.json` and supplied from the secret manager per §4.1 — never inlined.
- **Local Agent Memory (`memory`)**: `~/.claude.json` MUST define `@modelcontextprotocol/server-memory` writing to `/home/dev/.local/share/agent-memory/memory.json`. Agents MUST log facts, user preferences, and key architectural entities for sub-second retrieval across sessions.
- **Documentation MCPs (`context7`, `cf-docs`)**: Agents MUST query `context7` for open-source library/framework specs and `cf-docs`/`cf-bindings` for Cloudflare platform specs before generating implementation code.
- **Database & Persistence MCPs (`postgres`)**: Agents MUST use the `postgres` MCP tools to inspect table schemas, indexes, constraints, and cache keys instead of writing manual debug scripts. The `redis` MCP server is **not provisioned** — it failed to start on every session and was removed 2026-08-14; use `redis-cli` until a working server is configured.
- **Agent Gateway (`agent-gateway`) — LLM completions**: Agents MUST route LLM completions through `agent-gateway` at `https://gateway.infra.plexplease.com/v1`, which dynamically handles consumer OAuth load balancing (`CLIProxyAPI`) and local GPU offload (`Ollama`). That hostname was repointed from `gateway-engine` to the `agent-gateway` Service (port 8089) on 2026-09-11 and remains the single supported entrypoint. **There is no local endpoint.** `http://localhost:8089/v1` is documented here only to be ruled out: no local `agent-gateway` process runs, so the address refuses connections.
- **MCP Gateway (`bifrost`)**: The estate MCP gateway is **Bifrost** (`maximhq/bifrost`) at `https://mcp.infra.plexplease.com/mcp`, deployed to the `ai-gateway` namespace on 2026-09-11. Virtual-key enforcement on `/mcp` is NOT yet enabled (verified 2026-09-14; bootstrap deferred in the bifrost manifest): clients MUST NOT send `x-bf-vk` until it is — a wrong key is rejected, no key is accepted. This is a **distinct endpoint from the LLM completion path above** — MCP tool traffic goes to `mcp.infra.plexplease.com/mcp`, chat completions go to `gateway.infra.plexplease.com/v1`; neither serves the other's protocol. The Ingress is path-scoped to `/mcp`; Bifrost's UI, `/api/*` admin plane and `/metrics` are NOT exposed and MUST NOT be published without its own admin authentication configured.
- **Agent Tools Suite (`agent-tools`)**: Agents MUST use native `agent-tools` primitives for secrets (`internal/secrets` enforcing OpenBao merge-only patching, 1Password parent tracking, and RFC 3986 tokens) and standards enforcement (`internal/standards`).
- **Infra & DevOps MCPs (`argocd`, `grafana`, `homarr`, `agent-tools`)**: Use `argocd`/`grafana` MCP tools for deployment state and observability, and `agent-tools` primitives for Kubernetes diagnostics (`k8s_get`, `k8s_logs`), in-cluster HTTP (`http_request`) and estate lookup (`catalog_resolve`). **Prohibited**, hard-blocked by the `block-prohibited-docs.py` hook: `sshpass` → `remote_exec`; `kubectl exec … python3` pod probes → `http_request`/`k8s_get`; `op item get --reveal`/`--fields password|credential` → `secrets_1password_get`. Other raw `kubectl`/`docker` only when no primitive exists or for emergency triage.
- **Subagent MCP Equipping**: Subagents are spawned with the **`Agent` tool** (`subagent_type` selects the agent). User-scope MCP servers declared in `~/.claude.json` are reachable by every subagent automatically; schemas for deferred tools load on demand via `ToolSearch`. The real control is the agent definition: where a subagent type is defined in `.claude/agents/*.md`, its `tools:` frontmatter MUST retain the `mcp__<server>__<tool>` entries its task needs, because omitting them is what actually withdraws MCP access.

#### 1.5.1 Memory Tiering & Retrieval Protocol
- **Tier 1 (Fast Operational Memory - `memory`)**: Use `@modelcontextprotocol/server-memory` (JSON Knowledge Graph) for user preferences, tech stack choices, active sprint goals, entity relationships, and sub-second key-value lookups.
- **Tier 2 (In-Repo Specifications & Policy Workflows)**: Use version-controlled in-repo specifications (`docs/`, `config/`, and `homelab-policies/work/*.yaml`) for project architecture, ADRs, runbooks, and interface specs.

## Repository Documentation Minimalism

*Source: `Master-Policy.md` — summary; the full policy is in homelab-policies. Do not edit here.*

- **Rule (Decommissioned 2026-09-03):** Obsidian vault maintenance is **COMPLETELY DECOMMISSIONED**. The authoritative estate record is **machine-readable YAML/JSON** (`homelab-policies/policy/rules/*.yaml`, `homelab-policies/work/<project>.yaml`, and repo configuration files).
- **In-Repo Documentation Standard:** Code-adjacent documentation (`docs/`, architecture overviews, design decisions, runbooks, and interface specs) lives **exclusively in code repositories** under `docs/` adjacent to the implementations they describe.
- **AI-Agent First:** Agents MUST prioritize machine-readable structured formats (JSON/YAML) over loose unstructured markdown. When markdown is requested, it lives strictly in-repo under `docs/`.
- **Prohibited:** Maintaining hand-edited duplicate notes in external vaults. External markdown vault syncing is retired across the fleet.

## Modern Toolchain & Language Guidelines

*Source: `Coding-Standards-Policy.md` — do not edit here.*

### 2.1 Python (Modern Toolchain Mandate: `uv` & `ruff`)
- **Runtime Target:** Python 3.12+.
- **Mandatory Package & Environment Manager (`uv`):** Use **`uv`** (`uv pip`, `uv venv`, `uv sync`, `uv run`) for ultra-fast dependency resolution and virtual environment management. Traditional `pip` and `poetry` are deprecated.
- **[Nexus](CICD-Policy.md) PyPI Index Mandate:** All `uv` operations MUST target the local [Nexus](CICD-Policy.md) repository index at `https://nexus.infra.plexplease.com/repository/pypi-group/simple` via global `~/.config/uv/uv.toml` or repository-level `uv.toml`. *(Corrected 2026-08-12: this previously read `pypi-all`, which returns HTTP 404. Verified live — `pypi-group` returns 200.)*
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

**This table defines the informational timing benchmarks for test execution across all suites.** Test runners report execution duration and benchmarks for observability and performance telemetry rather than failing builds on strict caps.

| Tier | Scope of the benchmark | Informational Target |
|---|---|---|
| Tier 1 — Static analysis & lint | Whole repo | Informational; reports elapsed time |
| Tier 2 — Unit | Whole repo, entire unit suite | **~10 seconds** target (telemetry reported) |
| Tier 3 — Integration | Per suite | **~45 seconds** target (telemetry reported) |
| Tier 4 — E2E (mocked) | Own job, not part of the PR gate | **~60 seconds** target per suite |
| **CI fast-feedback telemetry (Tiers 1–2)** | Fast unit/lint PR check — aspirational feedback goal | **~60 seconds** aspirational target |
| **Heavy CI Pipelines (GitOps, Containers, SBOM)** | Full manifest validation, container baking, SBOM generation | **3–10 minutes** realistic runtime (thoroughness over speed) |

Notes:
- Tier 4 E2E runs against the `CLIProxyAPI` mock in its own job and is **excluded** from the Tiers 1–3 combined measurement.
- Test runners and CI telemetry report execution durations. Timing is tracked for performance regression analysis without failing builds solely on duration.
- Heavy workflows (e.g. `k8s` GitOps validation, container builds, golden images, and SBOM generation) naturally require 3–10 minutes. Builds MUST NOT be truncated or artificially constrained when comprehensive verification requires realistic execution time.

**Aspirational Target vs. Realistic Pipeline Execution (updated 2026-09-04).**
The 60-second benchmark is an aspirational target for developer feedback loops on simple code changes. For complex infrastructure validations, container image builds, and supply-chain security scans, correctness and rigorous empirical verification take precedence over arbitrary speed limits.

## Automated Quality Gates

*Source: `CICD-Policy.md` — do not edit here.*

Every Pull Request and commit MUST pass the following automated CI quality gates before code can be merged:
1. **MCP Scaffolding Gate — RETIRED 2026-08-14; guard relocated, clarified 2026-08-15.** MCP servers are configured once at user scope in `~/.claude.json`; repositories carry no `.mcp.json` or `.mcp.json.example`, so there is nothing in a checkout for CI to verify and the gate is removed from workflows. What retirement dropped is the requirement to **have** the file — it never licensed re-introducing one. The original instruction to "drop the `.mcp.json` checks from `scripts/setup_git_hooks.sh`" was accurate only about *where* the check lives: the guard moved rather than disappeared. It is now the `no-mcp-json` hook in each repo's `.pre-commit-config.yaml`, which fails any commit that stages `.mcp.json` or `.mcp.json.example`; `scripts/setup_git_hooks.sh` no longer writes hook bodies inline and only runs `pre-commit install` (reference implementation: `hardware`). A checkout whose hooks are not installed has no protection at all — running `pre-commit install` per clone and per worktree is what makes the ban real. Rationale — including why per-repo scaffolding never delivered its guarantee — is in [Master-Policy §1.5](Master-Policy.md).
2. **Static Analysis & Linting:** Code formatting and zero-warning lint checks (`ruff`, `biome`, `gofmt`).
3. **Security & Secret Scanning:** `gitleaks` over the checked-out tree, using a repo-local `.gitleaks.toml`, on every push and PR — **and in the Obsidian vault on the same footing**. Scope, allowlist discipline, and the sensitive-non-secret rules are defined in [Secrets-Policy §7](Secrets-Policy.md).
4. **Automated Test Matrix:** Execution of Unit and Integration test suites (Tiers 1–3). **Time caps are defined once in [Testing-Policy §3.1](Testing-Policy.md)** — do not restate a number here.
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
| `Master-Policy.md` | 2.4 | 2026-09-14 |
| `Secrets-Policy.md` | 4.0 | 2026-08-21 |
| `Testing-Policy.md` | 1.2 | 2026-08-13 |

<!-- END GENERATED — repo-specific directives may follow and are preserved. -->
