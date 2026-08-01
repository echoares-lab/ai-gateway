import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_OPERATIONS = (
    "clean-db",
    "docker",
    "compose",
    "volume",
    "dev-env.sh",
    "start-mock",
    "stop-mock",
)
pytestmark = pytest.mark.mock


def _render_test_mock(*args: str) -> list[str]:
    command = [
        "make",
        "--dry-run",
        "--no-print-directory",
        "test-mock",
    ]
    if args:
        command.append(f"MOCK_TEST_ARGS={' '.join(args)}")
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_mock_target_is_single_in_memory_recipe_with_optional_selectors():
    assert _render_test_mock() == ["python3 -m pytest tests/integration/ -m mock -v"]

    lines = _render_test_mock("-k", "sentinel_selector", "--lf")

    assert lines == ["python3 -m pytest tests/integration/ -m mock -v -k sentinel_selector --lf"]
    rendered = lines[0].lower()
    assert not any(operation in rendered for operation in FORBIDDEN_OPERATIONS)
