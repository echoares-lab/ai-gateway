"""Checker for the read_edit_verify_loop task."""
import re
import sys
from pathlib import Path

EXPECTED_COUNT = 6  # add, subtract, multiply, divide, square, is_even


def check(scratch_dir: Path) -> tuple[bool, str]:
    constants_py = scratch_dir / "constants.py"
    helpers_py = scratch_dir / "helpers.py"
    if not constants_py.exists():
        return False, "constants.py missing from scratch dir"
    if not helpers_py.exists():
        return False, "helpers.py missing from scratch dir"

    original_helpers = (Path(__file__).parent / "helpers.py").read_text()
    if helpers_py.read_text() != original_helpers:
        return False, "helpers.py was modified but should have been read-only"

    try:
        ns: dict = {}
        exec(compile(constants_py.read_text(), "constants.py", "exec"), ns)
    except Exception as e:  # noqa: BLE001
        return False, f"constants.py failed to exec: {e}"

    count = ns.get("FUNCTION_COUNT_PLACEHOLDER")
    if count != EXPECTED_COUNT:
        return False, f"FUNCTION_COUNT_PLACEHOLDER == {count!r}, expected {EXPECTED_COUNT} (int)"
    if ns.get("APP_NAME") != "sample-app":
        return False, "APP_NAME was modified"
    if ns.get("VERSION") != "1.0.0":
        return False, "VERSION was modified"

    return True, "ok"


if __name__ == "__main__":
    ok, reason = check(Path(sys.argv[1]))
    print("PASS" if ok else f"FAIL: {reason}")
    sys.exit(0 if ok else 1)
