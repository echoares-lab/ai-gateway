import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ops.validate_production_secrets import (
    REQUIRED_PRODUCTION_SECRETS,
    load_env_file,
    validate_secrets,
)


def _complete_values() -> dict[str, str]:
    return {name: f"production-value-{index}" for index, name in enumerate(REQUIRED_PRODUCTION_SECRETS, start=1)}


def test_complete_production_contract_passes() -> None:
    assert validate_secrets(_complete_values()) == []


@pytest.mark.parametrize("missing_name", REQUIRED_PRODUCTION_SECRETS)
def test_each_missing_secret_is_reported_without_echoing_values(missing_name: str) -> None:
    values = _complete_values()
    values.pop(missing_name)

    errors = validate_secrets(values)

    assert errors == [f"{missing_name} is missing"]
    assert "production-value" not in " ".join(errors)


@pytest.mark.parametrize("value", ["", "myredissecret", "changeme", "${REDIS_AUTH}"])
def test_empty_and_placeholder_values_are_rejected(value: str) -> None:
    values = _complete_values()
    values["REDIS_AUTH"] = value

    errors = validate_secrets(values)

    assert errors == ["REDIS_AUTH is empty or a development placeholder"]


def test_env_file_parser_ignores_comments_and_exports(tmp_path: Path) -> None:
    env_file = tmp_path / "production.env"
    env_file.write_text(
        "# comment\nexport REDIS_AUTH='secret value'\nLANGFUSE_DB_URL=postgres://prod\n",
        encoding="utf-8",
    )

    assert load_env_file(env_file) == {
        "REDIS_AUTH": "secret value",
        "LANGFUSE_DB_URL": "postgres://prod",
    }


def test_cli_returns_nonzero_and_only_names_for_invalid_file(tmp_path: Path) -> None:
    env_file = tmp_path / "production.env"
    env_file.write_text("REDIS_AUTH=myredissecret\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "scripts/ops/validate_production_secrets.py", str(env_file)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "REDIS_AUTH" in result.stderr
    assert "myredissecret" not in result.stdout + result.stderr
