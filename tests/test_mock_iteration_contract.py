import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_OPERATIONS = (
    "clean-db",
    "docker",
    "compose",
    "volume",
    "dev-env.sh",
    "start-mock",
    "stop-mock",
)


def _render_test_mock(*args: str) -> list[str]:
    result = subprocess.run(
        [
            "make",
            "--dry-run",
            "--no-print-directory",
            "test-mock",
            f"MOCK_TEST_ARGS={' '.join(args)}",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def test_mock_target_is_single_in_memory_recipe_with_optional_selectors():
    lines = _render_test_mock("-k", "sentinel_selector", "--lf")

    assert lines == ["python3 -m pytest tests/integration/ -m mock -v -k sentinel_selector --lf"]
    rendered = lines[0].lower()
    assert not any(operation in rendered for operation in FORBIDDEN_OPERATIONS)
