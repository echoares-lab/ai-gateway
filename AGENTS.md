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

*Source: `Master-Policy.md` — do not edit here.*

Reference: ADR 0001 - Obsidian-First Centralized Documentation Model.

- **Vault is the only documentation authority.** All project documentation — epics, task backlogs, ADRs, specs, architecture, runbooks, research reports, design/implementation plans, and status notes — lives **exclusively** in `/home/dev/obsidian-vault/01 Projects/<Project>/`.
- **Permitted markdown in a code repository (exhaustive list):**
  1. `README.md` — short orientation only: what the project is, how to run/test it, and a pointer to its vault folder. Not a place for architecture, epics, or status.
  2. `AGENTS.md` — the **canonical, version-controlled** agent-directive file (vendor-neutral: Claude, AGY, Codex, Cursor). This is the only directive file committed to a repository.
     - `CLAUDE.md` and other tool-specific directive files are **thin pointers to `AGENTS.md`**, kept **untracked and gitignored** (adopted 2026-08-10). They are local convenience only; never duplicate policy text into them, or the two copies drift.
  3. `CHANGELOG.md`, `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md` where the project genuinely needs them.
  4. Format/interface notes physically adjacent to the artifacts they describe (e.g. a data directory's `README.md` documenting a file schema consumed by code), kept to the minimum needed to use the files.
  5. Files under `.github/` that GitHub itself consumes or that document repository settings (e.g. `BRANCH_PROTECTION_POLICY.md`, issue templates) — amended 2026-08-12.
- **`TOOLING.md` — RETIRED 2026-08-15.** The per-repo tooling inventory admitted by the 2026-08-12 amendment is removed from the permitted list, deleted fleet-wide, and its template, index, and validator are dropped from `dev-policies`. It was write-once documentation that nothing consumed: 9 of 10 copies had a single commit and were never updated, no CI job or hook ever ran `validate-tooling-inventory.py`, and the first real run found the inventory already wrong. A stale inventory is worse than none — `ai-gateway`'s copy documented a `make help` target that does not exist. The dependency and tooling surface is `pyproject.toml` / `Makefile` / `package.json`, which are executable and cannot drift silently.
- **Prohibited in repositories:** `docs/` trees mirroring vault content, `TODO.md`, epic or sprint files, ADR folders, design/implementation plans, research reports, and status/progress documents. Agent tooling that defaults to writing plans or specs into the repo (e.g. `docs/superpowers/plans/`) MUST be redirected to the project's vault folder.
- **No "self-contained repo" exceptions.** Making a repo readable by agents lacking vault access is **not** a valid justification — agents have vault access, and duplication reproduces exactly the copy-drift ADR 0001 exists to prevent. Any pre-existing exception of this kind is revoked; migrate the content to the vault and delete the repo copy.
- **Vendored / upstream repositories are exempt.** Forks or vendored copies of third-party projects (currently `CLIProxyAPI`, `Cli-Proxy-API-Management-Center`) keep their upstream documentation in-repo: migrating it fights every upstream merge and destroys provenance. Only *locally authored* project documentation for such repos goes to the vault.
- **Code- and CI-consumed markdown is not documentation.** Files read at runtime, asserted by tests, served by an application, or targeted by an alert `runbook_url` are application/interface artifacts and stay in the repo (e.g. AI-Gateway's `docs/openapi/` served by `docs-server`; K3s-Cluster's four alert-linked runbooks; Cloudflare-Access-Automation's OpenAPI artifact and test fixtures). Where such a file must also exist in the vault, keep **one** authority and make the other a pointer stub — never two maintained copies.
  - **Clarified 2026-08-12:** `docs/runbooks/` and `docs/openapi/` are permitted **by path**, so this stops being re-litigated per file. A runbook qualifies when an alert's `runbook_url` (or equivalent live consumer) points at it — a runbook nothing links to is documentation and belongs in the vault.
- **Migration rule:** when removing documentation from a repo, **move** it into the vault (preserving content and history in the commit message), never delete outright.

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

> **Mount corrected 2026-08-16.** This clause previously mandated a `secret/` mount, which
> does not exist. `bao secrets list` returns exactly four mounts — `cubbyhole/`,
> `identity/`, `kv/` (KV-v2) and `sys/` — and the `openbao` ClusterSecretStore in `k3s-01`
> is configured `path: kv, version: v2`. Every `secret/data/agents/...` path written
> anywhere in this estate was unresolvable as stated. The policy was wrong; the
> infrastructure was consistent. Corrected here and in the Infra secrets-migration epics
> and audit. **Note the KV-v2 API quirk:** the `data/` segment appears in the HTTP path but
> **not** in `bao kv` commands or in an ExternalSecret `remoteRef.key`. The path above is
> addressed as `bao kv get kv/agents/...` and as `key: agents/...` with `path: kv` on the
> store.

- **`agent_type`**:
  - `autonomous`: Unattended background workers, cron jobs, K3s pod workloads, CI/CD pipelines.
  - `interactive`: Local developer coding agents (AGY, Codex, Cursor, Claude Code, Aider), interactive CLI tools.
- **`environment`**:
  - `prod`: Production cluster and live service workloads.
  - `staging`: Staging test environments.
  - `homelab`: Local homelab dev nodes and testing environments.
  - `global`: Environment-agnostic developer tools and global credentials.

### 2.2 Standardized `_metadata` Payload Schema

> **Known conflict with §2.1's commonest consumer pattern (recorded 2026-08-16).** Putting
> `_metadata` *inside* the payload means any consumer that reads the WHOLE secret receives it
> as a data key. In Kubernetes, a `dataFrom: extract:` ExternalSecret gains `_metadata` as an
> extra Secret key — observed on `ai-gateway-secrets` (29 → 30 keys) and its staging twin
> (18 → 19). It was inert in every case checked, because all consumers read by explicit
> `secretKeyRef` and nothing `envFrom`s a Secret — but that is a property of today's
> manifests, not a guarantee.
>
> **Until this is resolved, prefer explicit `data[].property` selection over
> `dataFrom: extract:` for any ExternalSecret reading an agent-scoped path.** Explicit
> selection is also what protects against the consolidation hazard in §2.4.
>
> Options for resolution, none yet chosen: exclude `_metadata` at extraction time; move
> provenance to OpenBao KV **custom metadata** (`kv metadata put`) instead of the payload,
> which keeps it out of every consumer entirely; or accept the extra key and state so
> explicitly.

Every secret payload stored in OpenBao MUST include a standard `_metadata` JSON object alongside credential keys:

```json
{
  "api_key": "[SECRET_VALUE]",
  "_metadata": {
    "owner": "team-or-handle",
    "repository": "https://github.com/org/repo-name",
    "allowed_agent_roles": ["k3s-01-external-secrets", "hardware-collector"],
    "max_ttl_seconds": 3600,
    "migrated_from": "kv/data/prod/platform/cloudflare",
    "created_at": "2026-08-11T00:00:00Z"
  }
}
```

### 2.3 Writers MUST merge, never replace (added 2026-08-16)

The KV-v2 write endpoint (`bao kv put`, `POST /v1/kv/data/<path>`) **replaces the entire
payload**. Any script that writes a subset of a secret's keys with `put` will silently delete
every key it does not set — including `_metadata`.

This is not hypothetical. Two scripts were caught mid-migration in the same week:

- `homelab-gitops/scripts/seed-openbao-kv.py` — one key into `cloudflare-platform/prod`
  (5 keys) and `truenas-storage/prod` (14 keys); a `put` would have taken down cert-manager,
  alertmanager, the breakglass SES watchdog, democratic-csi and the postgres backups.
- `k3s-01/scripts/create_nexus_service_account.py` — only `dockerconfigjson` into
  `nexus-registry/prod`, which also holds `username`, `password` and `_metadata` and is read
  by seven ExternalSecrets.

**Therefore: any writer that does not own every key at its path MUST use `bao kv patch`, or
a read-modify-write.** `put` is permitted only where the writer authoritatively owns the
whole payload.

### 2.4 Consolidated destinations (added 2026-08-16)

The 2026-08-11 dual-write **merged several legacy sources into single agent-scoped paths**.
Destinations are therefore not always one-to-one copies of their source, and may be
supersets:

| Destination | Holds | Consequence |
|---|---|---|
| `truenas-storage/prod` | TrueNAS + TrueNAS-S3 + MinIO (14 keys) | `prod/platform/truenas-s3` has no separate destination |
| `github-runner/prod` | 6 keys where the source had 1 | — |
| `server-partpicker/prod` | **31 keys where the source had 4** | a `dataFrom: extract:` repoint would have widened that namespace's Secret from 4 keys to 32, adding eBay and SES credentials |
| `aws-ses/prod` | 21 eBay/collector keys belonging to server-partpicker | **believed to be a mis-consolidation; needs review** |

Before repointing any consumer, compare the **key sets**, not just the values, and prefer
explicit key selection.

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
| `Master-Policy.md` | 2.1 | 2026-08-12 |
| `Secrets-Policy.md` | 3.3 | 2026-08-16 |
| `Testing-Policy.md` | 1.2 | 2026-08-13 |

<!-- END GENERATED — repo-specific directives may follow and are preserved. -->
