import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ops.validate_dev_env_slots import validate_slots


def _clean_slots() -> list[dict[str, str | int]]:
    return [
        {"slot": 1, "worktree": "/home/dev/worktrees/ai-gateway-one", "project": "aidev1", "state": "active"},
        {"slot": 2, "worktree": "/home/dev/worktrees/ai-gateway-two", "project": "aidev2", "state": "active"},
    ]


def test_clean_multi_slot_fixture_passes_with_stable_output() -> None:
    assert validate_slots(_clean_slots()) == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("slot", 0, "slot 0 is reserved"),
        ("project", "aidev9", "slot 1 must use Compose project aidev1"),
        ("state", "stale", "slot 1 has stale ownership"),
    ],
)
def test_unsafe_slot_metadata_is_rejected(field: str, value: str | int, message: str) -> None:
    records = _clean_slots()
    records[0][field] = value

    assert message in validate_slots(records)


def test_duplicate_slot_project_and_worktree_are_rejected() -> None:
    records = _clean_slots()
    records.append({"slot": 1, "worktree": records[1]["worktree"], "project": "aidev1", "state": "active"})

    errors = validate_slots(records)

    assert errors == [
        "duplicate slot: 1",
        "duplicate worktree: /home/dev/worktrees/ai-gateway-two",
        "duplicate Compose project: aidev1",
    ]


def test_cli_emits_names_only_and_nonzero_for_collision(tmp_path: Path) -> None:
    metadata = tmp_path / "slots.json"
    records = _clean_slots()
    records[0]["project"] = "aidev9"
    metadata.write_text(json.dumps(records), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/ops/validate_dev_env_slots.py", str(metadata)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "slot 1 must use Compose project aidev1" in result.stdout
    assert "/home/dev/worktrees" not in result.stdout
