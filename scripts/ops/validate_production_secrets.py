#!/usr/bin/env python3
"""Validate the non-optional production secret contract.

The command accepts a dotenv-style file containing *names and values* supplied
to a deployment. It never prints values, making it safe to use in CI logs.
The source of truth for these names is the OpenBao contract documented in
``01 Projects/AI-Gateway/Specs/CICD_PHASE2_CD_K3S.md``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Environment names are the stable interface consumed by the workloads. The
# corresponding OpenBao keys are documented alongside the production manifests.
REQUIRED_PRODUCTION_SECRETS = (
    "LANGFUSE_DB_URL",
    "REDIS_AUTH",
    "CLICKHOUSE_PASSWORD",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "NEXTAUTH_SECRET",
    "LANGFUSE_SALT",
    "LANGFUSE_ENCRYPTION_KEY",
)

_PLACEHOLDER_RE = re.compile(
    r"(?:\$\{[^}]+\}|op://|(?:^|\b)(?:changeme|change-me|example|"
    r"placeholder|mysecret|myredissecret|miniosecret|minioadmin|"
    r"replace[-_ ]?me)(?:\b|$))",
    re.IGNORECASE,
)


def load_env_file(path: Path) -> dict[str, str]:
    """Read a small dotenv file without requiring a third-party parser."""

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"line {line_number} is not KEY=VALUE")
        name, value = line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
            raise ValueError(f"line {line_number} has invalid variable name")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[name] = value
    return values


def validate_secrets(values: dict[str, str]) -> list[str]:
    """Return safe, name-only validation errors for the production contract."""

    errors: list[str] = []
    for name in REQUIRED_PRODUCTION_SECRETS:
        if name not in values:
            errors.append(f"{name} is missing")
            continue
        value = values[name].strip()
        if not value or _PLACEHOLDER_RE.search(value):
            errors.append(f"{name} is empty or a development placeholder")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("env_file", type=Path, help="dotenv file to validate")
    args = parser.parse_args()
    try:
        errors = validate_secrets(load_env_file(args.env_file))
    except (OSError, ValueError) as exc:
        print(f"production secret contract error: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("Production secret contract failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Production secret contract passed ({len(REQUIRED_PRODUCTION_SECRETS)} names checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
