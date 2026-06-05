#!/usr/bin/env python3
"""Promote validated policy profiles from Git config into Postgres (P0-7)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "policy-engine"))

from profile_promotion import (  # noqa: E402
    _default_profiles_path,
    load_policy_profiles_file,
    parse_policy_profiles,
    validate_policy_profiles,
)

_UPSERT_SQL = """
INSERT INTO policy_profiles (
    profile_id, scope, scope_id, allowed_models, denied_models,
    fallback_chain_override, credential_tier_preference, policy_json, enabled
) VALUES (
    %(profile_id)s, %(scope)s, %(scope_id)s, %(allowed_models)s, %(denied_models)s,
    %(fallback_chain_override)s, %(credential_tier_preference)s,
    %(policy_json)s::jsonb, %(enabled)s
)
ON CONFLICT (scope, scope_id) DO UPDATE SET
    profile_id = EXCLUDED.profile_id,
    allowed_models = EXCLUDED.allowed_models,
    denied_models = EXCLUDED.denied_models,
    fallback_chain_override = EXCLUDED.fallback_chain_override,
    credential_tier_preference = EXCLUDED.credential_tier_preference,
    policy_json = EXCLUDED.policy_json,
    enabled = EXCLUDED.enabled,
    updated_at = now()
"""


def _load_database_url() -> str | None:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _profile_row(profile) -> dict:
    return {
        "profile_id": profile.profile_id,
        "scope": profile.scope.value,
        "scope_id": profile.scope_id,
        "allowed_models": profile.allowed_models,
        "denied_models": profile.denied_models,
        "fallback_chain_override": profile.fallback_chain_override,
        "credential_tier_preference": profile.credential_tier_preference,
        "policy_json": json.dumps(profile.policy_json),
        "enabled": profile.enabled,
    }


def promote_profiles(path: str | Path | None, *, apply: bool, database_url: str | None) -> int:
    profiles_path = Path(path) if path else _default_profiles_path()
    data, load_errors = load_policy_profiles_file(profiles_path)
    if load_errors:
        print(f"✗ Pre-flight failed for {profiles_path}", file=sys.stderr)
        for err in load_errors:
            print(f"  • {err}", file=sys.stderr)
        return 1

    assert data is not None
    errors = validate_policy_profiles(data)
    if errors:
        print(
            f"✗ Pre-flight: {len(errors)} validation error(s) — aborting promotion:",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        print("Keeping existing Postgres policy_profiles rows unchanged.", file=sys.stderr)
        return 1

    profiles = parse_policy_profiles(data)
    print(f"✓ Pre-flight: {len(profiles)} profile(s) validated in {profiles_path}")

    if not apply:
        for profile in profiles:
            print(f"  • {profile.profile_id} ({profile.scope.value}/{profile.scope_id})")
        print("Dry-run complete. Re-run with --apply to upsert into Postgres.")
        return 0

    if not database_url:
        print("✗ DATABASE_URL is required for --apply", file=sys.stderr)
        return 1

    try:
        import psycopg2
    except ImportError:
        print("✗ psycopg2 is required for --apply (pip install psycopg2-binary)", file=sys.stderr)
        return 1

    try:
        conn = psycopg2.connect(database_url)
    except Exception as exc:  # noqa: BLE001
        print(f"✗ Postgres connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        with conn:
            with conn.cursor() as cur:
                for profile in profiles:
                    cur.execute(_UPSERT_SQL, _profile_row(profile))
        print(f"✓ Promoted {len(profiles)} profile(s) to policy_profiles")
    except Exception as exc:  # noqa: BLE001
        print(f"✗ Promotion failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=None, help="Policy profiles YAML path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Upsert validated profiles into Postgres (default: dry-run only)",
    )
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL")
    args = parser.parse_args(argv)

    database_url = args.database_url or _load_database_url()
    return promote_profiles(args.path, apply=args.apply, database_url=database_url)


if __name__ == "__main__":
    raise SystemExit(main())
