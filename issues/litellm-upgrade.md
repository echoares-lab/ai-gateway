---
work_type: type:code-health
summary: Upgrade LiteLLM to v1.87.1 for performance, new model support, and enhanced telemetry.
problem: |
  Current deployment uses an older, pinned version of LiteLLM (sha256:7c311546...).
  1. Missing "Day 0" support for OpenAI o1/o3 and Gemini 3.x models.
  2. Not leveraging Granian engine for improved ASGI performance.
  3. Lacks advanced OTEL telemetry features found in 2026 releases.
why_now: Upgrading to the latest stable release ensures compatibility with new model architectures and improves gateway throughput/observability.
scope: |
  - Upgrade LiteLLM image in docker-compose.yml and docker-compose.dev.yml to v1.87.1.
  - Document the LiteLLM upgrade procedure in RUNBOOK.md.
  - Follow-up (this issue): Tune settings for Granian, OTEL, and DB connection pooling.
non_goals:
  - Immediate enablement of Granian or OTEL (deferred to separate PR for stability).
  - Changes to the translator logic or LiteLLM configuration.
acceptance:
  - [ ] LiteLLM is running v1.87.1.
  - [ ] LiteLLM UI is functional at :4001.
  - [ ] `./cliproxy-setup.sh health` passes.
  - [ ] Model routing works (e.g., `./cliproxy-setup.sh test gemini-3-flash`).
  - [ ] RUNBOOK.md contains instructions for future LiteLLM upgrades.
tests: |
  Gate B: make test-mock (run in CI)
  Gate D: cliproxy-setup.sh health + model smoke tests on stable
risks: |
  - Regressions in model routing due to internal LiteLLM mapping changes.
  - Database migration requirements (LiteLLM usually handles this on startup).
  - Rollback: Revert the sha256 image digest and restart.
dependencies:
  - cliproxy-cpa-upgrade.md
files:
  - docker-compose.yml
  - docker-compose.dev.yml
  - RUNBOOK.md
execution_notes: |
  The follow-up performance tuning should consider:
  - Setting `LITELLM_USE_GRANIAN=true` in .env.
  - Configuring OpenTelemetry endpoints for advanced observability.
  - Tuning `PRISMA_IO_TIMEOUT` and connection pool settings if high-load is expected.
---
