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


def _test_mock_declaration_and_recipe() -> tuple[str, list[str]]:
    lines = (ROOT / "Makefile").read_text().splitlines()
    target_index = lines.index("test-mock:")
    recipe = []
    for line in lines[target_index + 1 :]:
        if not line.startswith("\t"):
            break
        recipe.append(line.removeprefix("\t"))
    return lines[target_index], recipe


def test_mock_target_is_single_in_memory_recipe_with_optional_selectors():
    makefile = (ROOT / "Makefile").read_text()
    declaration, recipe = _test_mock_declaration_and_recipe()

    assert "MOCK_TEST_ARGS ?=" in makefile
    assert declaration == "test-mock:"
    assert recipe == ["python3 -m pytest tests/integration/ -m mock -v $(MOCK_TEST_ARGS)"]
    rendered = recipe[0].lower()
    assert not any(operation in rendered for operation in FORBIDDEN_OPERATIONS)
