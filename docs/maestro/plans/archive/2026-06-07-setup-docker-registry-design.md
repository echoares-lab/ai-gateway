---
title: "Docker Registry Integration"
created: "2026-06-08T04:10:00Z"
status: "approved"
authors: ["TechLead", "User"]
type: "design"
design_depth: "quick"
task_complexity: "medium"
---

# Docker Registry Integration Design Document

## Problem Statement
The AI Gateway project currently relies on locally built Docker images. While this works for the current self-hosted CI runner, it creates several bottlenecks:
1. **Distribution**: There is no central source of truth for the "production" versions of the images.
2. **Traceability**: Hard to verify exactly which commit an image came from once it's on the runner.
3. **Remote Deployment**: Deploying the stack to a new environment requires rebuilds from source rather than simple `docker pull`.

## Requirements

### Functional Requirements
1. **Automated Publishing**: Push core service images to GHCR on successful CI runs.
2. **Standardized Naming**: Images must follow the `ghcr.io/echoares-lab/ai-gateway/<service>` convention.
3. **Versioned Tagging**: Tag images with the short `GIT_SHA` and `latest`.

### Constraints
- **Registry**: Use GitHub Container Registry (GHCR).
- **Scope**: Core services only (`gateway-engine`, `cliproxy`, `litellm-reloader`).

## Approach

### Selected Approach: GitHub Container Registry (GHCR) Integration
We will integrate GHCR into the existing CI pipeline to serve as the project's central image repository.

**Key Technical Decisions:**
- **Authentication**: Leverage the built-in `GITHUB_TOKEN` in the CI workflow for zero-config `docker login`.
- **Registry Path**: `ghcr.io/echoares-lab/ai-gateway/`.
- **Tagging Strategy**: 
  - Every build will push an image tagged with the short `GIT_SHA` for immutability.
  - Successful merges to `main` will also update the `latest` tag for convenience.
- **Image Names**: 
  - `gateway-engine`
  - `cliproxy`
  - `litellm-reloader`
- **Visibility**: Images will be public initially to simplify access on self-hosted runners (avoiding complex secret management).

## Agent Team

| Phase | Agent(s) | Parallel | Deliverables |
|-------|----------|----------|--------------|
| 1     | devops_engineer | No       | GHCR Login & Script Updates |
| 2     | devops_engineer | No       | Docker Compose Registry Standardization |
| 3     | devops_engineer | No       | CI Pipeline Push Logic |
| 4     | tester | No       | Deployment Validation |

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Build/Push Failure | MEDIUM | LOW | CI workflow will fail-fast if registry authentication or pushing fails. |
| Pipeline Latency | LOW | MEDIUM | Use Docker Buildx GHA caching to minimize redundant layer pushes. |
| Unauthorized Usage | LOW | LOW | Public images contain no secrets; sensitive logic remains protected by API keys at runtime. |

## Success Criteria
1. Images for `gateway-engine`, `cliproxy`, and `litellm-reloader` are visible at `ghcr.io/echoares-lab/ai-gateway`.
2. CI pipeline completes both building and pushing for every merge to `main`.
3. Production stack remains deployable via `docker compose pull && docker compose up`.
