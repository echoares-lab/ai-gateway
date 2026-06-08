# Environment Promotion & Config Release Channels

> **Status:** Design. Foundational model for [Roadmap Epic #35 — Environment promotion and config release channels](https://github.com/echoares-lab/ai-gateway/issues/35).
> This document defines the boundaries between file-based configuration and database state, outlines the environment promotion stages, details safe rollout and rollback strategies, and presents a phased implementation plan.

---

## 1. Source of Truth Boundaries

To prevent configuration drift and operational outages, the gateway enforces a strict boundary between static, version-controlled configurations and dynamic, database-backed runtime states.

### 1.1 Static File Configuration (Git-Tracked)
File-based configuration is static, tracked in Git, and deployed via standard environment updates. File configuration is the absolute source of truth for structural topology:

| Configuration Area | Target Files | Primary Settings | Runtime Policy |
|---|---|---|---|
| **Model Registry** | `litellm-config.yaml` | Model definitions, aliases, upstreams, base URLs, costs, and request/response scopes. | Read-Only. Direct additions or removals must be merged to main. |
| **Routing Topology** | `litellm-config.yaml` | Fallback matrices, adaptive routing settings (`routing_strategy`, `cooldown_time`, `allowed_fails`). | Read-Only. |
| **System Tools** | `litellm-config.yaml` | MCP server registrations (FS, Git, Search, PostgreSQL) and command line arguments. | Read-Only. |
| **Stack Topology** | `docker-compose.yml` | Service definitions, exposed ports, volume mappings, and container base images. | Read-Only. Requires container recreation. |
| **Global Secrets** | `.env` | Provider API keys (`BRAVE_API_KEY`, etc.), internal tokens, and master credentials. | Read-Only. gitignored. |

### 1.2 Dynamic Database State (Runtime-Driven)
Database and cache states represent runtime allocations, permissions, and audit logs. They are dynamic, read-write, and managed programmatically or via operator panels:

| State Area | Storage Layer | Primary Content | Naming Convention |
|---|---|---|---|
| **Virtual API Keys** | PostgreSQL / Redis | Temporary client keys, scopes, limits, and team associations. | `ak-{org}-{workspace}-{team}-{repo}-{env}` |
| **Teams & Budgets** | PostgreSQL | Workspace groups, RPM/TPM rate limit rules, and dollar budgets. | `{org}-{workspace}-{team}` |
| **Credential Inventory** | PostgreSQL | Provider account status, fail counters, cooldown timestamps. | `cred-{org}-{provider}-{id}` |
| **Trace Metrics** | PostgreSQL (Langfuse) | LLM request traces, prompt/completion tokens, and performance metrics. | Run-time generated UUIDs |

---

## 2. Config Promotion Pipeline

Configuration changes must move through a structured promotion pipeline to guarantee that syntax errors, schema drift, or broken upstreams are caught before hitting production traffic.

```text
  [ Developer Workspace ] ──> Local validation & dev-slot testing (Slot 1-9)
            │
            ▼
  [ Pull Request (CI) ]   ──> Linting, syntax check, and mock-tier integration tests
            │
            ▼
  [ Staging Stack ]       ──> Deployment to staging slot, E2E checks with real credentials
            │
            ▼
  [ Production Stack ]    ──> Merge to main, pull config, validate, hot-reload LiteLLM
```

### 2.1 Stage 1: Local & Dev Slot Verification
1. The developer modifies `litellm-config.yaml` or compose files inside a git worktree.
2. The developer launches an isolated dev slot (e.g. Slot 1) using `./dev-env.sh start 1`.
3. The developer verifies changes by running local unit tests (`docker exec aidev1-gateway-engine-1 pytest test_gateway-engine.py`).

### 2.2 Stage 2: Pull Request & CI Gate
1. The developer pushes the branch and creates a PR to `main`.
2. GitHub Actions runs the CI Suite:
   - **`lint-and-syntax`**: Verifies YAML syntax (`yaml.safe_load`), Ruff lint rules, and bash script syntax.
   - **`mock-integration`**: Builds the gateway-engine/LiteLLM images and executes the mock test suite.
3. The PR cannot be merged if any automated check fails.

### 2.3 Stage 3: Staging E2E Testing (Gated)
1. Promoted configurations are deployed to a dedicated staging slot mapping to production-like environments.
2. The staging runner runs E2E model checks against real consumer accounts (using `cliproxy` OAuth credentials) to verify routing and fallback paths work on live endpoints.

### 2.4 Stage 4: Production Release
1. The PR is merged to `main`.
2. The production gateway pulls the updated files.

---

## 3. Rollout & Rollback Strategy

LiteLLM and the gateway-engine support dynamic configuration updates, but restarting containers carries risk. We implement a **fail-safe hot-reload workflow** in the reloader service.

```text
       Config Change Detected
                 │
                 ▼
     [ Pre-Flight Validation ] ────(Fail)───> Log Error & Retain Old Config
                 │
               (Pass)
                 ▼
      [ Graceful Container Restart ]
                 │
                 ▼
        [ Post-Start Probe ] ──────(Fail)───> Restore Backup & Restart Reloader
                 │
               (Pass)
                 ▼
       Rollout Complete (OK)
```

### 3.1 Pre-Flight Validation
Before initiating a reload or restart, the reloader script must run offline checks:
- **YAML Validation**: Parse configuration via a YAML validator to ensure it has no format anomalies.
- **Model Schema Check**: Ensure all model definitions contain the required parameters (`model_name`, `litellm_params`).
- **MCP Server Check**: Verify that registered MCP servers point to existing local commands or valid SSE hosts.

If pre-flight validation fails, the rollout is aborted. The previous working configuration is retained, and a `CRITICAL` alert is dispatched.

### 3.2 Post-Start Probe & Auto-Rollback
Once the LiteLLM container is restarted, the reloader monitors its startup:
1. **Health Check Probe**: Polls LiteLLM's `/health` (or `/v1/models`) endpoint every 2 seconds.
2. **Timeout Boundary**: If LiteLLM fails to reach a healthy status within 45 seconds (e.g. due to database connection timeout or invalid configuration schema), a rollback is triggered.
3. **Rollback Action**:
   - Replace the active config file with the backup of the previous configuration.
   - Force restart the LiteLLM container.
   - Raise a high-severity alert webhook notifying operators of the failure and rollback event.

---

## 4. Phased Implementation Plan

We propose splitting the execution of Epic #35 into the following sequenced child issues:

   Add offline YAML parsing and model validation to the `watch.py` script before triggering container restarts.
2. **#100 -- feat(config): implement post-start health checks and auto-rollback**
   Add a monitoring loop to `watch.py` that rolls back to a backup configuration if LiteLLM fails to boot within a 45-second timeout.
3. **#101 -- ci(config): add GitHub Action workflow job to validate config schema**
   Add a YAML lint and schema validation step to the Pull Request CI pipeline to catch configuration mistakes before code is merged.

---

## 5. References
- [Tenancy & Workspace Domain Model](./TENANCY.md)
- [Unified Admin Console Design](./ADMIN_CONSOLE.md)
- [Roadmap Status](./ROADMAP.md)
- [Repo Improvement Workflow](../REPO_IMPROVEMENT_WORKFLOW.md)
