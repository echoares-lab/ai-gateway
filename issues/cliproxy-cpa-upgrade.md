---
work_type: type:code-health
summary: Upgrade CLIProxyAPI to v7.1.45 and pin cpa-manager to v1.5.5 for stability and reliability.
problem: |
  Current deployment uses pinned CLIProxyAPI v7.1.22 and unpinned cpa-manager:latest.
  1. CLIProxyAPI v7.1.22 is behind the latest release (v7.1.45).
  2. Unpinned cpa-manager:latest can lead to unpredictable deployments if breaking changes are introduced.
why_now: Keeping core OAuth relay and management components up-to-date ensures security, bug fixes, and operational stability.
scope: |
  - Upgrade CLIProxyAPI binary in Dockerfile.cliproxy.
  - Pin cpa-manager image in docker-compose.yml, docker-compose.dev.yml, and docker-compose.mock.yml.
  - Document the upgrade procedure in RUNBOOK.md for future maintainers.
non_goals:
  - Changes to the translator logic or LiteLLM configuration.
  - Changes to the management UI features themselves.
acceptance:
  - [ ] cliproxy is running v7.1.45.
  - [ ] cpa-manager is running v1.5.5.
  - [ ] `./cliproxy-setup.sh health` passes.
  - [ ] Model routing works (e.g., `./cliproxy-setup.sh test gemini-3-flash`).
  - [ ] RUNBOOK.md contains instructions for future upgrades.
tests: |
  Gate B: make test-mock (run in CI)
  Gate D: cliproxy-setup.sh health + model smoke tests on stable
risks: |
  - Breaking changes in CLIProxyAPI config format (minimal risk between 7.1.x versions).
  - Registry unavailability for the new images.
  - Rollback: Revert version numbers and rebuild.
dependencies:
  None.
files:
  - Dockerfile.cliproxy
  - docker-compose.yml
  - docker-compose.dev.yml
  - docker-compose.mock.yml
  - RUNBOOK.md
---
