# CLIProxy Upstream-Patch Migration and Dependency Updates — Design

**Date:** 2026-07-17  
**Status:** Approved for implementation through epic #413 atomic children  
**Primary systems:** CLIProxyAPI fork, ai-gateway CI, and k3s-01 staging/production overlays

## Goal

Replace the drifting CLIProxyAPI fork with current upstream plus the smallest
locally owned quota patch stack, then put cliproxy and every third-party runtime
dependency through a documented update, validation, promotion, and rollback
loop. Production continues to use immutable image digests.

## Non-goals

- Carry fork auth-hardening already supplied by upstream.
- Keep unused batch credential management endpoints.
- Float `:latest` in production or auto-merge high-risk updates.
- Change Gemini CLI retirement scope from epic #386.
- Reimplement dependency or promotion work in this coordination issue.

## Patch-stack decision

The reset issue must compare the 11 fork-only commits in oldest-to-newest order
before rewriting history. The rows below are the complete disposition contract;
CLIProxyAPI #12 records the corresponding old SHA beside each row in its PR so
the frozen `6cf6e68` lineage remains auditable after reset.

| Fork order | Change represented by the fork commit | Source | Decision | Reason |
|-----------:|----------------------------------------|--------|----------|--------|
| 1 | Require management authentication on credential mutations | Closed CLIProxyAPI #1 | Drop | Current upstream protects the same management surface; carrying both implementations creates divergent auth behavior. |
| 2 | Restrict credential file paths and identifiers | Closed CLIProxyAPI #2 | Drop | The upstream implementation supersedes this hardening and should remain the single source of truth. |
| 3 | Harden management credential reads and error responses | Closed CLIProxyAPI #3 | Drop | The behavior overlaps upstream and is not an independently required gateway contract. |
| 4 | Add batch credential create/import request types | Superseded batch work | Drop | No ai-gateway production or operator flow calls the batch API. |
| 5 | Add batch credential mutation handlers | Superseded batch work | Drop | Unused management surface increases maintenance and security exposure. |
| 6 | Register batch credential management routes | Superseded batch work | Drop | Routes are unnecessary after dropping batch request types and handlers. |
| 7 | Add batch credential handler tests and fixtures | Superseded batch work | Drop | Tests cover functionality intentionally removed from the patch stack. |
| 8 | Adjust batch credential validation and partial-failure responses | Superseded batch work | Drop | The gateway does not consume this contract; upstream behavior wins. |
| 9 | Follow-up compatibility fix for batch credential operations | Superseded batch work | Drop | Retaining a compatibility patch for a removed endpoint has no value. |
| 10 | Add quota status foundation and provider window model | Closed CLIProxyAPI #6 | Re-port | Gateway `/admin/quota/status` depends on normalized per-account quota windows. |
| 11 | Add live quota refresh contract and partial-status semantics | Closed CLIProxyAPI #5 | Re-port | Deep-smoke quota assertions require the live contract and explicit fresh/unsupported/missing/error states. |

The target branch is upstream plus at most two new commits: one quota foundation
commit and one live-contract commit. These are clean re-ports, not cherry-picks
that preserve unrelated ancestry. CLIProxyAPI #13 owns the re-port and must
prove both the fork tests and ai-gateway quota contract before a candidate image
is published.

## Upstream tracking model

CLIProxyAPI #11 establishes a weekly scheduled track:

1. Fetch the canonical `router-for-me/CLIProxyAPI` default branch and identify
   the exact upstream SHA.
2. Rebase or reconstruct the two-commit quota stack on that SHA in a candidate
   branch; fail on conflicts rather than silently carrying old resolutions.
3. Run upstream tests, quota-specific tests, static checks, and an image build.
4. Publish a Nexus candidate tagged with immutable source identity, including
   upstream SHA and patch-head SHA. A moving convenience tag may point to it in
   staging but is never promoted directly.
5. Dispatch or expose the candidate to the ai-gateway promotion workflow. No
   production pin changes merely because the weekly job succeeded.
6. Open an actionable PR or issue containing upstream range, patch range, image
   digest, test results, release notes, and rollback digest.

A failed rebase, failed quota contract, missing provenance, or failed image scan
stops candidate publication. Patch count greater than two is drift and requires
an explicit design update before promotion.

## Cliproxy promotion gate

Cliproxy uses the same candidate path as gateway-engine:

1. Resolve the Nexus candidate tag to an immutable digest.
2. Pin that digest in the isolated `ai-gateway-staging` overlay.
3. Wait for ArgoCD sync and workload readiness.
4. Run staging deep-smoke `--full`; quota assertions are hard failures.
5. Open the k3s-01 production pin PR with the exact tested digest, staging
   revision, deep-smoke evidence, previous production digest, and rollback
   command.
6. After production sync, verify image ID, Gateway health, three provider-family
   model smokes, and quota summary. Record Gate D evidence.

Automatic dispatch may create the staging candidate or a production pin PR, but
it may not skip deep-smoke. Existing emergency `skip_deep_smoke` behavior
remains an explicit operator-only exception and must be recorded.

## Dependency inventory and Renovate policy

CLIProxyAPI's weekly job owns fork/upstream tracking because Renovate cannot
reconstruct a local Go patch stack. Renovate owns discoverable image and
configuration pins in ai-gateway. Issue #416 records every occurrence across
compose, environment defaults, documentation examples, and k3s overlays.

| Component | Update source | Risk | Update policy |
|-----------|---------------|------|---------------|
| CLIProxyAPI / cliproxy | Weekly upstream-track candidate in Nexus | High | No auto-merge; immutable candidate digest; full staging gate |
| LiteLLM | Renovate image digest/tag update | High | No auto-merge; separate PR; wire-contract and DB review |
| gateway-engine | Repository CI image | High | Existing CI plus full staging gate before production pin |
| CPA-Manager | Renovate image update | Medium | Group only compatible patch/minor updates; UI/API smoke |
| Langfuse web and worker | Renovate image update | Medium | Keep both services on one version; trace and worker smoke |
| ClickHouse | Renovate image update | Medium | Separate migration/storage review; backup and query smoke |
| MinIO | Renovate image update | Medium | Storage/API compatibility and object read/write smoke |
| Redis | Renovate image update | Low–medium | Patch/minor grouping; config and cache health checks |
| Postgres | Renovate image update | Low–medium | No automatic major update; backup/restore and extension review |

Renovate package rules label PRs by risk, prevent high-risk automerge, separate
major updates, and attach the required gate checklist. Digest pinning must not
hide the human-readable version. All runtime images, including transitive
Langfuse services, belong in the inventory.

## Per-component gates and rollback

| Component | Required pre-promotion evidence | Production verification | Rollback |
|-----------|---------------------------------|-------------------------|----------|
| cliproxy | Fork tests; quota contract; image scan; staging `--full`; auth PVC compatibility | Image ID, health, claude/gpt/gemini smokes, quota summary | Revert to prior digest; restore OpenBao `cliproxy_auth_tar_b64` only if token format changed |
| LiteLLM | Gate A/B; config validation; staging `--full`; migration review; Gate C for provider/auth changes | Models, API shapes, spend log, provider smokes | Revert image first; restore DB only from a pre-update backup when migration is not backward-compatible |
| gateway-engine | Required CI Gates A/B; staging `--full`; Gate C for auth/routing | Health, version, provider smokes, quota | Re-promote prior digest |
| CPA-Manager | Compose validation; startup and management UI/API smoke | UI reachable and usage ingestion current | Revert prior digest/tag; preserve SQLite volume |
| Langfuse web/worker | Compose validation; migration review; staging trace ingestion and worker health | New trace searchable; workers healthy | Revert both images together; database restore only with documented migration incompatibility |
| ClickHouse / MinIO | Config validation; backup; storage health and read/write smoke | Langfuse ingestion and retrieval | Restore prior image and compatible data snapshot |
| Redis | Config validation; unit/mock suite; cache health | Health and representative request | Revert minor/digest; flush disposable cache only when serialization changed |
| Postgres | Config validation; backup/restore proof for major changes; service integration tests | DB readiness, migrations, spend logging | Revert only when on-disk format permits; otherwise restore backup into the prior major version |

Every update PR identifies the old and new version/digest, relevant release-note
range, schema/config changes, required gates, observed results, and exact
rollback target. Unknown migration reversibility blocks production promotion.

## Rollback drill and evidence

Before closing epic #413, operators perform one staging cliproxy drill:

1. Record candidate digest N, previous digest N-1, Argo revision, and auth archive
   reference.
2. Promote N to staging and pass deep-smoke `--full`.
3. Revert staging to N-1 without copying staging credentials into production.
4. Confirm readiness and deep-smoke `--full` on N-1.
5. Restore N, rerun the gate, and attach timestamps and results to #413.

The drill fails if any digest is mutable, if credentials need undocumented
manual repair, or if rollback cannot restore a green deep-smoke.

## Dependency order

Task #414 promotes this design. CLIProxyAPI #12 then resets the fork, followed
by quota re-port #13 and weekly tracking #11. In ai-gateway, #415 and #416 may
run independently after #414; #417 follows #416. Cutover #418 requires the new
quota image and preferably #415. Cleanup #419 runs only after production
cutover. The parent epic remains unclaimable.

## Success criteria

- The CLIProxy fork is current with upstream and carries no more than two quota
  commits.
- Weekly tracking produces auditable immutable candidates without changing
  production.
- Cliproxy promotion cannot bypass staging deep-smoke on the normal path.
- Every third-party runtime pin has an owner, risk tier, gate, and rollback.
- The staging rollback drill succeeds and is linked from the epic closeout.
