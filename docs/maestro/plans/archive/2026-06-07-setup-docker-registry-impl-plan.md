---
title: "Docker Registry Integration Implementation Plan"
design_ref: "/home/dev/repos/ai-gateway/docs/maestro/plans/2026-06-07-setup-docker-registry-design.md"
created: "2026-06-08T04:15:00Z"
status: "approved"
total_phases: 4
estimated_files: 8
task_complexity: "medium"
---

# Docker Registry Integration Implementation Plan

## Plan Overview
- **Total phases**: 4
- **Agents involved**: `devops_engineer`, `tester`
- **Estimated effort**: Moderate refactoring of CI workflows and Docker Compose configurations.

## Dependency Graph
```text
[Phase 1: Foundation]
       |
[Phase 2: Registry Config]
       |
[Phase 3: CI/CD Push Logic]
       |
[Phase 4: Validation]
```

## Execution Strategy
| Stage | Phases | Execution | Agent Count | Notes |
|-------|--------|-----------|-------------|-------|
| 1     | 1, 2, 3 | Sequential | 1 | Standard infrastructure layering |
| 2     | 4      | Sequential | 1 | Final verification |

## Phase 1: Foundation: Build Arguments and Login
### Objective
Set up `GIT_SHA` exports and registry login in scripts and workflows.
### Agent: devops_engineer
### Parallel: No
### Files to Modify
- `scripts/ci-build-mock-services.sh`
- `.github/workflows/ci.yml`
### Implementation Details
- Update `scripts/ci-build-mock-services.sh` to accept optional registry path prefix.
- Ensure CI workflow exports `GIT_SHA` correctly before build steps.
- Add `docker login ghcr.io` using `GITHUB_TOKEN`.
### Validation
- Build script executes locally without errors.
- CI configuration is syntactically valid.

## Phase 2: Registry Standardization: Docker Compose
### Objective
Add `image:` keys to core services in Compose files using the `ghcr.io` path.
### Agent: devops_engineer
### Parallel: No
### Files to Modify
- `docker-compose.yml`
- `docker-compose.dev.yml`
### Implementation Details
- Add `image: ghcr.io/echoares-lab/ai-gateway/<service-name>:${GIT_SHA:-latest}` to `gateway-engine`, `cliproxy`, and `litellm-reloader`.
- Ensure build arguments are preserved.
### Validation
- `docker compose config` passes with no warnings.

## Phase 3: Workflow Implementation: Build and Push
### Objective
Update CI to build, tag, and push images to GHCR.
### Agent: devops_engineer
### Parallel: No
### Files to Modify
- `.github/workflows/ci.yml`
### Implementation Details
- Update `build-docker-cached` action usage or equivalent build steps to include `--push` flag (or `docker push`).
- Ensure push only happens on `main` or specific PR events.
### Validation
- PR shows successful build steps.

## Phase 4: Validation: Registry Pulls
### Objective
Verify images can be successfully pulled from GHCR.
### Agent: tester
### Parallel: No
### Files to Modify
- `tests/test-gateway-e2e.sh`
### Implementation Details
- Attempt `docker pull` of the generated images in a clean environment (if possible) or verify registry visibility.
### Validation
- Images are pullable and verifiable via `docker inspect`.

---

## File Inventory
| # | File | Phase | Purpose |
|---|------|-------|---------|
| 1 | `scripts/ci-build-mock-services.sh` | 1 | Foundation for mock image naming |
| 2 | `.github/workflows/ci.yml` | 1, 3 | Core CI logic updates |
| 3 | `docker-compose.yml` | 2 | Production stack image naming |
| 4 | `docker-compose.dev.yml` | 2 | Development stack image naming |
| 5 | `tests/test-gateway-e2e.sh` | 4 | Verification script |

## Risk Classification
| Phase | Risk | Rationale |
|-------|------|-----------|
| 1 | LOW | Script updates are additive. |
| 2 | LOW | Standard config change. |
| 3 | MEDIUM | Directly impacts CI pipeline success; requires correct auth. |
| 4 | LOW | Read-only verification. |

## Execution Profile
```
Execution Profile:
- Total phases: 4
- Parallelizable phases: 0
- Sequential-only phases: 4
- Estimated sequential wall time: 20-30 minutes

Note: Native subagents currently run without user approval gates.
All tool calls are auto-approved without user confirmation.
```
