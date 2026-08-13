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

- **Local Agent Memory (`memory`)**: Every repository MUST include `.mcp.json` with `@modelcontextprotocol/server-memory` configured to write to `/home/dev/.local/share/agent-memory/memory.json`. Agents MUST log facts, user preferences, and key architectural entities for sub-second retrieval across sessions.
- **Obsidian Vault Memory (`obsidian`)**: Every repository MUST include `.mcp.json` with Obsidian MCP configured (`obsidian-mcp-server` or `mcp-obsidian`). Agents MUST read/write specs, ADRs, and project documentation in `/home/dev/obsidian-vault/01 Projects/<Project>/`.
- **New Repository Scaffolding Mandate**: Whenever creating, scaffolding, or cloning a new repository, agents MUST automatically create a root `.mcp.json` file preconfigured with `memory` and `obsidian` MCP servers.
- **`.mcp.json` is LOCAL and gitignored; `.mcp.json.example` is COMMITTED (resolved 2026-08-12).** The working `.mcp.json` carries a live `OBSIDIAN_API_KEY` and MUST NOT be committed — §4.1 forbids it, and it is gitignored in every repository. This directly contradicted the CI gate in CICD-Policy §1.1.1, which required CI to verify a file CI can never legitimately see: the gate was unsatisfiable without leaking a credential, and `.mcp.json` is in fact untracked in 11 of 13 repositories.
  - **What is committed:** `.mcp.json.example` — same server definitions, every credential replaced by a `<PLACEHOLDER>`. This is what CI verifies.
  - **What is not:** the working `.mcp.json`, supplied per-machine from the secret manager.
  - **The scaffolding requirement is unchanged** — a repository must still be *able* to run `memory` and `obsidian`; the example file is the committed evidence that it is configured to.
- **Documentation MCPs (`context7`, `cf-docs`)**: Agents MUST query `context7` for open-source library/framework specs and `cf-docs`/`cf-bindings` for Cloudflare platform specs before generating implementation code.
- **Database & Persistence MCPs (`postgres`, `redis`)**: Agents MUST use `postgres` and `redis` MCP tools to inspect table schemas, indexes, constraints, and cache keys instead of writing manual debug scripts.
- **Infra & DevOps MCPs (`kubernetes`, `docker`, `homarr`)**: Agents MUST use `kubernetes` and `docker` MCP tools for checking container builds, pod statuses, and service health during development.
- **Subagent MCP Equipping**: Every spawned subagent (`invoke_subagent` / `define_subagent`) MUST be initialized with `enable_mcp_tools: true` so background agents can leverage the full MCP suite (including `memory` and `obsidian`).

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
  5. `TOOLING.md` — the human-audited tooling/dependency surface for the repository (amended 2026-08-12). This is deliberate fleet infrastructure, not drift: it follows a shared template, is indexed across repos, and pairs with the `sbom.yml` workflow. Native manifests remain the dependency source of truth; `TOOLING.md` is the audit view over them.
  6. Files under `.github/` that GitHub itself consumes or that document repository settings (e.g. `BRANCH_PROTECTION_POLICY.md`, issue templates) — amended 2026-08-12.
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
1. **MCP Scaffolding Gate:** Verification that root **`.mcp.json.example`** exists and defines the `memory` (`@modelcontextprotocol/server-memory`) and `obsidian` (`obsidian-mcp-server` / `mcp-obsidian`) servers. **Corrected 2026-08-12:** this gate previously named `.mcp.json`, which is gitignored in every repo because it carries a live `OBSIDIAN_API_KEY` — CI could never see it, so the gate was unsatisfiable without violating §4.1. See Master-Policy §1.5.
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

`secret/data/agents/{agent_type}/{agent_id}/{environment}/`

- **`agent_type`**:
  - `autonomous`: Unattended background workers, cron jobs, K3s pod workloads, CI/CD pipelines.
  - `interactive`: Local developer coding agents (AGY, Codex, Cursor, Claude Code, Aider), interactive CLI tools.
- **`environment`**:
  - `prod`: Production cluster and live service workloads.
  - `staging`: Staging test environments.
  - `homelab`: Local homelab dev nodes and testing environments.
  - `global`: Environment-agnostic developer tools and global credentials.

### 2.2 Standardized `_metadata` Payload Schema
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
| `CICD-Policy.md` | 1.2 | 2026-08-12 |
| `Coding-Standards-Policy.md` | 1.1 | 2026-08-12 |
| `Git-Policy.md` | 1.0 | 2026-07-29 |
| `Master-Policy.md` | 2.1 | 2026-08-12 |
| `Secrets-Policy.md` | 3.1 | 2026-08-12 |
| `Testing-Policy.md` | 1.2 | 2026-08-13 |

<!-- END GENERATED — repo-specific directives may follow and are preserved. -->




