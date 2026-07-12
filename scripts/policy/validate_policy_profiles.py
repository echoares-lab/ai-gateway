#!/usr/bin/env python3
"""Pre-flight validation for config/policy-profiles.yaml (P0-7, CONFIG_PROMOTION.md)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "gateway-engine"))

from core.policy.profile_promotion import (  # noqa: E402
    _default_profiles_path,
    load_policy_profiles_file,
    validate_policy_profiles,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        default=None,
        help="Policy profiles YAML path (default: config/policy-profiles.yaml)",
    )
    args = parser.parse_args(argv)

    profiles_path = Path(args.path) if args.path else _default_profiles_path()
    data, load_errors = load_policy_profiles_file(profiles_path)
    if load_errors:
        print(f"✗ {profiles_path}: validation FAILED", file=sys.stderr)
        for err in load_errors:
            print(f"  • {err}", file=sys.stderr)
        return 1

    assert data is not None
    errors = validate_policy_profiles(data)
    if errors:
        print(
            f"✗ {profiles_path}: {len(errors)} schema error(s)",
            file=sys.stderr,
        )
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        return 1

    profile_count = len(data.get("profiles") or [])
    print(f"✓ {profiles_path}: schema OK, {profile_count} profile(s) validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
