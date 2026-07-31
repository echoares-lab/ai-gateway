#!/usr/bin/env python3
"""Apply the offline config promotion gate and emit an auditable record."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.ops.validate_config_promotion import validate_contract
except ModuleNotFoundError:  # direct execution from the repository root
    from validate_config_promotion import validate_contract


def build_promotion_record(document: dict[str, Any], *, verified_by: str) -> dict[str, Any]:
    artifact = document["artifact"]
    promotion = document["promotion"]
    return {
        "artifact": artifact["name"],
        "version": artifact["version"],
        "digest": artifact["digest"],
        "source_revision": artifact["source_revision"],
        "target": promotion["target"],
        "verified_by": verified_by,
        "rollback": promotion["rollback"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("--verified-by", required=True)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    try:
        document = json.loads(args.metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "errors": [f"metadata unreadable: {type(exc).__name__}"]}))
        return 2

    errors = validate_contract(document, target="production")
    if errors:
        print(json.dumps({"status": "blocked", "errors": errors}))
        return 1

    record = build_promotion_record(document, verified_by=args.verified_by)
    args.record.parent.mkdir(parents=True, exist_ok=True)
    args.record.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "promoted", "record": record}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
