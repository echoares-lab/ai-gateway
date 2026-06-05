---
work_type: type:coordination
summary: Agent dispatch index for Epic #38 Policy Engine — phase order, parallel lanes, claiming rules.
problem: |
  Multiple agents implementing Epic #38 need a single source for issue order, parallel
  lanes, and claim_status without duplicating work on hotspots.
why_now: |
  Atomic issues policy-engine-38-01..38-21 created per POLICY_ENGINE_AND_ROUTING_REFACTOR.md §10.
scope: |
  - Phase order 0 → 5
  - Parallel lanes per phase
  - Claim protocol cross-reference to REPO_IMPROVEMENT_WORKFLOW.md §8
  - Live claim_status summary (update when claiming)
non_goals:
  - Replacing GitHub issues (mirror for repo-local agents)
acceptance:
  - [ ] All child issue files listed with dependencies
  - [ ] Parallel lanes documented
  - [ ] Quota-aware issues flagged (38-1, 38-7, 38-9, 38-10, 38-11)
tests: |
  N/A — coordination doc
dependencies:
  - issues/policy-engine-epic-38.md
  - REPO_IMPROVEMENT_WORKFLOW.md
files:
  - issues/policy-engine-*.md
claim_status: not-claimable
github_issue: #141
---

# Policy Engine Dispatch — Epic #38

**Epic:** [policy-engine-epic-38.md](./policy-engine-epic-38.md)  
**Phase 0 gate:** [policy-engine-phase0-prerequisites.md](./policy-engine-phase0-prerequisites.md)  
**Design:** [docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md](../docs/POLICY_ENGINE_AND_ROUTING_REFACTOR.md)

## Claiming rules

1. Pick the **lowest-phase, unblocked** issue with `claim_status: unassigned`.
2. Post start-work comment with `Claim-ID: <agent>-<host>-<utc-timestamp>` per REPO_IMPROVEMENT_WORKFLOW.md §8.
3. Set `claim_status: claimed-by-<agent-id>` in the issue file frontmatter.
4. On completion, set `claim_status: done` and record PR link in issue body.
5. **Do not claim** epic parent or Phase 0 tracking issue for implementation.
6. **Hotspot rule:** `services/policy-engine/schemas.py` is owned by 38-1 (done) — additive changes only via new issues.

## Phase order

| Phase | Name | Issues |
|-------|------|--------|
| 0 | Prerequisites (tracking) | [phase0-prerequisites](./policy-engine-phase0-prerequisites.md) |
| 1 | Skeleton | 38-01, 38-02, 38-03, 38-04 |
| 2 | Core policies | 38-05 … 38-09 |
| 3 | Key pool refactor | 38-10 … 38-14 |
| 4 | Control plane | 38-15 … 38-18 |
| 5 | Advanced (optional) | 38-19 … 38-21 |

## Parallel lanes

```text
Phase 0 (parallel design — no translator wire):
  38-01 schemas ─────────────┐
  38-10 pool migration ──────┘  (both may complete before Phase 0 gate clears)

Phase 1 (after 38-01 done):
  38-02 scaffold ──┬── 38-03 redis      (parallel after 38-02)
                 └── 38-04 translator  (parallel after 38-02; shared env needs P0-1..P0-3)

Phase 2 (after 38-03; 38-04 for 38-9):
  38-05 repo affinity ───┐
  38-06 agent affinity ──┼── parallel
  38-07 rate-limit agg ──┘   (quota-aware core)
  38-09 budget gates ──────── after 38-04 + P0-4
  38-08 fallback eval ─────── after 38-05, 38-06, 38-07

Phase 3:
  38-11 pool aliases ── after 38-10
  38-12 prober events ─ after 38-07 + P0-6
  38-13 cliproxy sync ─ after 38-11 (optional)
  38-14 websocket ───── after 38-04

Phase 4:
  38-15 admin trace ── after 38-04
  38-16 audit log ──── after 38-08
  38-17 integration ─ after 38-08, 38-14
  38-18 runbook ────── after 38-15

Phase 5 (optional, parallel when unblocked):
  38-19, 38-20, 38-21 — each independent after their blocked_by list clears
```

## Quota-aware issues (first-class)

| Issue | Quota-aware scope |
|-------|-------------------|
| 38-01 | QuotaHeadroom, RateLimitSnapshot, quota_aware_mode on RoutingDecision |
| 38-07 | Redis cooldown registry, pre-emptive deprioritization, rolling 429 threshold |
| 38-09 | Soft gate via quota headroom % |
| 38-10 | credential_pools.affinity_mode includes quota-aware |
| 38-11 | Pool routing sets quota_aware_mode for CLIProxy path |
| 38-02 | Evaluator stub documents quota-aware path |

Reference: [ROUTING_AND_FAILOVER_STRATEGY.md](../docs/ROUTING_AND_FAILOVER_STRATEGY.md) §3.

## Claim status board

| Issue | claim_status | Notes |
|-------|--------------|-------|
| phase0-prerequisites | tracking | Not claimable |
| epic-38 | not-claimable | Parent coordination |
| 38-01 schemas | **done** | Quota-aware schemas shipped |
| 38-02 scaffold | **done** | Stub evaluator + tests |
| 38-03 redis | **done** | Cooldown registry, agent affinity, profile/decision cache keys |
| 38-04 translator | **in-review** | PR #156 — `POLICY_ENGINE_ENABLED` hook + unit tests; agent `142a1b91` lane superseded |
| 38-05 repo affinity | **done** | Postgres read + repo affinity + Redis profile cache |
| 38-06 agent affinity | **done** | Agent affinity evaluator wired |
| 38-07 rate-limit | **done** | Aggregator wired; inventory + Redis + translator merge |
| 38-08 fallback | **done** | Layered evaluator + 11 unit tests (#127, PR #144) |
| 38-09 budget | **done** | Soft gates + fail-open hard deny (#128, PR #142) |
| 38-10 pool schema | **done** | Migration 002 in repo |
| 38-11 pool aliases | **done** | Tier alias docs + claude-sonnet-4-6-at-native |
| 38-12 prober events | **done** | POST /v1/events/credential + prober notifier |
| 38-13 cliproxy sync | unassigned | Optional; blocked: 38-11 |
| 38-14 websocket | **done** | PR #156 — Option B bypass + design doc §9; closes #133 |
| 38-15 admin trace | **in-review** | PR #156 — `policy_engine` panel in `/admin/status`; closes #134 on merge |
| 38-16 audit log | **done** | PR #145 (merge queue) |
| 38-17 integration tests | unassigned | Blocked: 38-14 |
| 38-18 runbook | unassigned | Blocked: 38-15 |
| 38-19 eval routing | unassigned | Optional Phase 5 |
| 38-20 mcp visibility | unassigned | Optional Phase 5 |
| 38-21 chargeback | unassigned | Optional Phase 5 |

## Merge queue closeouts (2026-06-05)

Batch merged to `main`: **#142** (38-9 budget), **#143** (38-12 prober), **#144** (38-8 fallback), **#145** (38-16 audit). Issue files below record PR links.

## Next agent action

**Claim:** [policy-engine-38-13-cliproxy-priority-sync.md](./policy-engine-38-13-cliproxy-priority-sync.md) (optional) or [policy-engine-38-04-translator.md](./policy-engine-38-04-translator.md) (blocked on P0-1..P0-3).

**Done:** 38-9 budget ([#128](./policy-engine-38-09-budget-gates.md), PR #142); 38-16 audit ([#135](./policy-engine-38-16-audit-log.md), PR #145).

## Live claim_status summary

| Issue | claim_status | GitHub |
|-------|--------------|--------|
| 38-01 schemas | done | #120 |
| 38-02 scaffold | done | #121 |
| 38-03 redis | done | #122 |
| 38-05 repo affinity | done | — |
| 38-06 agent affinity | done | — |
| 38-07 rate-limit | done | #126 |
| 38-08 fallback | done | #127, PR #144 |
| 38-16 audit log | done | #135, PR #145 |
| 38-04 translator | **in-review** | PR #156 — `POLICY_ENGINE_ENABLED` hook + unit tests; agent `142a1b91` lane superseded |
| 38-06 agent affinity | done | #125 |
| 38-10 pool schema | done | #129 |
| 38-12 prober events | done | #131 |
| Phase 0 prerequisites | tracking (not claimable) | #119 |
| Epic coordination | not-claimable | #38 |

**Next unblocked for implementation:** 38-13 cliproxy sync (optional; PR #146 in review). **38-04** remains gated on P0-1..P0-3 per phase0 prerequisites.