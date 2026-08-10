# Mandatory Policy & Agent Behavior Directives for AGY, Codex, Cursor & Claude

## 1. Knowledge Authority & Discovery Protocol (Self-Contained Project Model)
All project documentation, architectures, tech stack choices, ADR decisions, active work, and epics live **exclusively inside self-contained project folders** in the Obsidian vault at:
`/home/dev/obsidian-vault/01 Projects/<Project-Name>/`

### Standardized Project Folder Schema:
- **Overview.md**: Project summary, scope, and any project-specific **Policy Exceptions**.
- **Architecture.md**: System architecture & design specs for this project.
- **Tech-Stack.md**: Approved technologies & dependency choices for this project.
- **Todo.md**: Active sprint tasks & epic backlog for this project.
- **ADRs/**: Architectural Decision Records specific to this project (e.g. `0001-title.md`).
- **Runbooks/**: Operational runbooks, deployment guides, and troubleshooting specs.
- **Specs/**: Technical design specs, API contracts, and feature specifications.

### Fast Context Discovery & Recall Rules:
1. **Context Load Order:** Read `/home/dev/obsidian-vault/02 Areas/Policies/Master-Policy.md` first, then inspect `01 Projects/<Project>/Overview.md` for local `## Policy Exceptions`.
2. **Mandatory MCP Tool Suite:**
   - **`context7`**: Always query `context7` for authoritative framework & library documentation (FastAPI, Pydantic, SQLAlchemy, Pytest, Hono, etc.) when implementing or refactoring features.
   - **Cloudflare MCP Suite (`cf-docs`, `cf-bindings`, `cf-observability`)**: Always use `cf-docs` for Cloudflare platform specs, `cf-bindings` for Worker bindings (D1, KV, R2, Queues), and `cf-observability` for tail logs.
   - **Database MCP Suite (`postgres`, `redis`)**: Use `postgres` and `redis` MCP tools for sub-second table schema lookups, index verification, and cache inspection instead of writing manual debug scripts.
   - **Infra & DevOps MCP Suite (`kubernetes`, `docker`, `homarr`)**: Use `kubernetes` and `docker` MCP tools for inspecting pod statuses, container layers, and homelab services.
3. **LSP over Regex:** Use Language Server Protocol (Serena LSP) or `obsidian-mcp-server` tools over raw regex grep for fast, accurate symbol and note lookups.
4. **Wikilink Traversal:** Follow Obsidian wikilinks `[[Note-Name]]` directly via `obsidian_get_note` or `view_file` rather than searching blindly.
5. **Subagent MCP Equipping:** When spawning or defining subagents (`invoke_subagent` / `define_subagent`), agents MUST equip them with MCP tools (`enable_mcp_tools: true`) so subagents access `context7`, `obsidian`, `cf-docs`, `cf-bindings`, `postgres`, `redis`, `kubernetes`, `docker`, `serena`, `homarr`, and `playwright`.
6. **Offload Heavy Research:** Use `invoke_subagent` (`research` / `investigator`) for multi-file research to preserve main thread context window.

## 2. Mandatory Toolchains & Infrastructure Mandates
1. **Python Toolchain (`uv`):** All Python package management, virtual environment creation, and execution MUST use `uv` (`uv pip`, `uv venv`, `uv run`, `uv sync`). Traditional `pip` and `poetry` are deprecated.
2. **Nexus PyPI Index:** All `uv` operations MUST target the local Nexus repository index at `https://nexus.infra.plexplease.com/repository/pypi-group/simple`.
3. **Container Registry & Versioning:** All container images MUST be published exclusively to local Nexus Registry (`https://nexus-registry.infra.plexplease.com`) using **Semantic Versioning ONLY** (`v1.0.0`). Mutable tags (`latest`) and Git SHAs are strictly prohibited.
4. **GitOps First:** All K3s cluster deployments MUST be managed via **ArgoCD** and `homelab-gitops`. Direct manual `kubectl` or `docker` execution on production nodes is prohibited.

## 3. Strict Code Execution & Diagnostics
1. **No Masking Errors:** Fix underlying root causes. Never swallow exceptions, return dummy fallbacks, or comment out failing unit tests.
2. **Mandatory Run Verification:** Always execute build and test commands (`npm test`, `pytest`, `go test`, `cargo test`) before declaring completion.

## 4. OpenBao and Cloudflare Worker Secrets
1. **Source of Truth:** Automation credentials belong in OpenBao at their service-scoped KV path. Worker runtime credentials are encrypted Cloudflare Worker secrets, never `wrangler.toml` variables or repository files.
2. **Bootstrap:** Use a 1Password-held OpenBao administrator credential only when a human explicitly authorizes a bootstrap operation. The bootstrap AppRole has a stored `role_id` but no standing `secret_id`; mint a short-lived SecretID just in time, destroy it by accessor, and revoke the resulting bootstrap token after the operation.
3. **Transfer safety:** Validate that an OpenBao field read succeeds and is non-empty before supplying it to `wrangler secret put`. Never print secret values, command-substitute them into logged text, or commit them.
4. **Required bindings:** When code needs a Worker secret, add only its name to `wrangler.toml`'s `[secrets].required` list. Confirm configured names with `./scripts/run_wrangler.sh secret list`.

## 5. External API Documentation & Verification Protocol
1. **Authoritative Local Spec Note**: Every external API or third-party vendor (e.g. Icecat, Sold-Comps, eBay, Amazon, Cloudflare) MUST maintain a dedicated, versioned specification note under `01 Projects/<Project>/Specs/<vendor>-api-reference.md`.
2. **Dual-Tier Retrieval**: Before changing endpoint paths, credentials, rate-limiting, or error handling for an external vendor API, agents MUST inspect the local vault spec note first. If updating or integrating a new vendor API, use `context7`, `cf-docs`, `cf-bindings`, or `search_web`/`read_url_content` to fetch live documentation, then update the vault spec note.
3. **Empirical Verification over Assumptions**: Document measured behavior (rate-limit backoff, 429 Retry-After, 403 vs 404 error semantics) alongside official documentation claims.

## Repository Documentation Minimalism (Obsidian-First)

Per [[02 Areas/Policies/Master-Policy.md|Master-Policy §1.6]] and Engineering-Standards ADR 0001, **all** project documentation — epics, backlogs, ADRs, specs, architecture, runbooks, reports, and design/implementation plans — lives **exclusively** in `/home/dev/obsidian-vault/01 Projects/<Project>/`.

Permitted markdown in a repo (exhaustive): `README.md` (brief orientation + vault pointer only), `AGENTS.md`/`CLAUDE.md`, standard `LICENSE`/`CHANGELOG`/`CONTRIBUTING`/`SECURITY`, and minimal format notes adjacent to the artifacts they describe (e.g. a data directory schema note).

**Prohibited:** `docs/` trees mirroring vault content, `TODO.md`, epic/sprint files, ADR folders, plans, reports, status docs. Redirect agent tooling that defaults to writing plans into the repo (e.g. `docs/superpowers/plans/`) to the vault project folder. "Self-contained repo" is **not** a valid exception — move such content to the vault rather than duplicating it.
