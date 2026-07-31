#!/usr/bin/env python3
"""Validate sanitized dev-slot ownership before Docker Compose actions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate_slots(records: list[dict[str, Any]]) -> list[str]:
    """Return deterministic, metadata-only collision errors."""

    errors: list[str] = []
    seen_slots: set[int] = set()
    seen_projects: set[str] = set()
    seen_worktrees: set[str] = set()
    for record in records:
        slot = record.get("slot")
        worktree = record.get("worktree")
        project = record.get("project")
        state = record.get("state", "active")
        if not isinstance(slot, int) or isinstance(slot, bool):
            errors.append("slot must be a positive integer")
            continue
        if slot == 0:
            errors.append("slot 0 is reserved")
        elif slot < 0:
            errors.append(f"slot {slot} must be positive")
        if slot in seen_slots:
            errors.append(f"duplicate slot: {slot}")
        seen_slots.add(slot)
        expected_project = f"aidev{slot}"
        if project != expected_project:
            errors.append(f"slot {slot} must use Compose project {expected_project}")
        if not isinstance(worktree, str) or not worktree:
            errors.append(f"slot {slot} must identify a worktree")
        elif worktree in seen_worktrees:
            errors.append(f"duplicate worktree: {worktree}")
        else:
            seen_worktrees.add(worktree)
        if isinstance(project, str) and project in seen_projects:
            errors.append(f"duplicate Compose project: {project}")
        if isinstance(project, str):
            seen_projects.add(project)
        if state != "active":
            errors.append(f"slot {slot} has stale ownership")
    return errors


def records_from_projects(projects: list[str]) -> list[dict[str, Any]]:
    """Build ownership metadata from Compose project labels reported by Docker."""

    records: list[dict[str, Any]] = []
    for index, project in enumerate(projects, start=1):
        slot_text = project.removeprefix("aidev") if project.startswith("aidev") else "invalid"
        try:
            slot: int | str = int(slot_text)
        except ValueError:
            slot = slot_text
        records.append({"slot": slot, "worktree": f"reported-{index}", "project": project, "state": "active"})
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path, nargs="?", help="JSON list of sanitized slot metadata")
    parser.add_argument("--projects", help="newline-separated Compose project labels reported by Docker")
    args = parser.parse_args()
    try:
        if (args.metadata is None) == (args.projects is None):
            raise ValueError("provide exactly one metadata file or --projects")
        if args.projects is not None:
            records = records_from_projects([line for line in args.projects.splitlines() if line])
        else:
            records = json.loads(args.metadata.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise ValueError("metadata must be a JSON list")
        errors = validate_slots(records)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid-input", "error": str(exc)}, sort_keys=True))
        return 2
    report = {"errors": errors, "status": "collision" if errors else "clean", "slots_checked": len(records)}
    print(json.dumps(report, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
