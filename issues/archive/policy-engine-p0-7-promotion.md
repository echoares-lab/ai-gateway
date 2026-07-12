---
work_type: type:feature
summary: P0-7 — Pre-flight validation and promotion path for git-tracked policy profiles.
claim_status: done
claimed_by: cursor-575k-20260605
acceptance:
  - [x] config/policy-profiles.yaml is the git-tracked promotion source
  - [x] profile_promotion.py validates PolicyProfile rows and policy_json sections
  - [x] scripts/validate_policy_profiles.py runs offline pre-flight checks (CI Gate B)
  - [x] scripts/promote_policy_profiles.py validates before Postgres upsert (--apply)
  - [x] Unit tests cover valid/invalid profile documents
dependencies:
  - issues/policy-engine-phase0-prerequisites.md (P0-7)
  - docs/CONFIG_PROMOTION.md
  - services/policy-engine/schemas.py (PolicyProfile)
---

# P0-7 — Policy Profile Promotion Validation

Implements the CONFIG_PROMOTION.md pre-flight gate for `policy_profiles` before
they are promoted from Git into Postgres.

## Validate (CI + local)

```bash
python3 scripts/validate_policy_profiles.py
```

## Promote (operator)

```bash
# Dry-run (default) — validation only
python3 scripts/promote_policy_profiles.py

# Apply after migration 002_policy_profiles_pools.sql
python3 scripts/promote_policy_profiles.py --apply
```

Requires `DATABASE_URL` (or `.env`) when using `--apply`. Promotion aborts on any
schema error and leaves existing Postgres rows unchanged.
