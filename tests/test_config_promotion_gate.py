from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.ops.promote_config_artifact import build_promotion_record

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/config_promotion"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_promotion_record_contains_auditable_identity() -> None:
    record = build_promotion_record(_load("clean.json"), verified_by="staging-deep-smoke/2026-07-31")
    assert record == {
        "artifact": "litellm-config",
        "version": "2026.07.31.1",
        "digest": "sha256:" + "a" * 64,
        "source_revision": "0123456789abcdef0123456789abcdef01234567",
        "target": "production",
        "verified_by": "staging-deep-smoke/2026-07-31",
        "rollback": {
            "version": "2026.07.30.4",
            "digest": "sha256:" + "b" * 64,
        },
    }


def test_gate_writes_record_for_clean_artifact(tmp_path: Path) -> None:
    record = tmp_path / "promotion-record.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/ops/promote_config_artifact.py",
            str(FIXTURES / "clean.json"),
            "--verified-by",
            "staging-deep-smoke/2026-07-31",
            "--record",
            str(record),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(record.read_text(encoding="utf-8"))["target"] == "production"


def test_gate_blocks_stale_artifact_without_record(tmp_path: Path) -> None:
    record = tmp_path / "blocked.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/ops/promote_config_artifact.py",
            str(FIXTURES / "stale.json"),
            "--verified-by",
            "staging-deep-smoke/2026-07-31",
            "--record",
            str(record),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "blocked" in result.stdout
    assert not record.exists()
