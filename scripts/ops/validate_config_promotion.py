#!/usr/bin/env python3
"""Validate sanitized config-artifact promotion metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def validate_contract(document: dict[str, Any], *, target: str) -> list[str]:
    errors: list[str] = []
    artifact = document.get("artifact")
    promotion = document.get("promotion")
    if not isinstance(artifact, dict):
        return ["artifact metadata is required"]
    if not isinstance(promotion, dict):
        return ["promotion metadata is required"]

    for field in ("name", "version", "digest", "source_revision", "environment"):
        if not artifact.get(field):
            errors.append(f"artifact.{field} is required")
    digest = artifact.get("digest", "")
    if digest and not _DIGEST.fullmatch(str(digest)):
        errors.append("artifact.digest must be an immutable sha256 digest")
    revision = artifact.get("source_revision", "")
    if revision and not _REVISION.fullmatch(str(revision)):
        errors.append("artifact.source_revision must be a full git revision")
    if artifact.get("environment") not in ("staging", "production"):
        errors.append("artifact.environment must be staging or production")
    if promotion.get("target") != target:
        errors.append("promotion.target does not match requested target")

    if target == "production":
        if artifact.get("environment") != "staging":
            errors.append("production promotion must originate from staging")
        if promotion.get("verified") is not True:
            errors.append("production promotion requires verified=true")
        if promotion.get("verified_digest") != digest:
            errors.append("verified digest must match artifact digest")
        rollback = promotion.get("rollback")
        if not isinstance(rollback, dict) or not rollback.get("version") or not rollback.get("digest"):
            errors.append("rollback metadata is required")
        elif rollback.get("digest") == digest:
            errors.append("rollback digest must differ from artifact digest")
        elif not _DIGEST.fullmatch(str(rollback.get("digest"))):
            errors.append("rollback.digest must be an immutable sha256 digest")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--target", choices=("staging", "production"), required=True)
    args = parser.parse_args()
    try:
        document = json.loads(args.metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"errors": [f"metadata unreadable: {type(exc).__name__}"]}))
        return 2
    errors = validate_contract(document, target=args.target)
    print(json.dumps({"errors": errors, "status": "clean" if not errors else "invalid"}))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
