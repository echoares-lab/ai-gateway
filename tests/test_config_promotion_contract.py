from __future__ import annotations

import json
from pathlib import Path

from scripts.ops.validate_config_promotion import validate_contract

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/config_promotion"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_clean_staging_to_production_contract_passes() -> None:
    assert validate_contract(_load("clean.json"), target="production") == []


def test_stale_verified_digest_is_rejected() -> None:
    errors = validate_contract(_load("stale.json"), target="production")
    assert "verified digest must match artifact digest" in errors


def test_missing_rollback_metadata_is_rejected() -> None:
    errors = validate_contract(_load("missing_rollback.json"), target="production")
    assert "rollback metadata is required" in errors


def test_staging_target_does_not_require_production_verification() -> None:
    assert validate_contract(_load("staging.json"), target="staging") == []
