"""Checker for the single_edit task.

Usage: python checker.py <scratch_dir>
Prints "PASS" or "FAIL: <reason>" and exits 0/1 accordingly.
"""

import sys
from pathlib import Path

MARKER = "TODO_UNIQUE_MARKER_7f3a"
EXPECTED_LINE = 'GREETING = "Hello, benchmark!"'


def check(scratch_dir: Path) -> tuple[bool, str]:
    app_py = scratch_dir / "app.py"
    if not app_py.exists():
        return False, "app.py missing from scratch dir"

    original = (Path(__file__).parent / "app.py").read_text().splitlines()
    current = app_py.read_text().splitlines()

    if MARKER in current:
        return False, "marker line was not replaced"

    if EXPECTED_LINE not in current:
        return False, "expected replacement line not found"

    # Every other line must be unchanged (same content, same relative order).
    orig_without_marker = [line for line in original if MARKER not in line]
    current_without_replacement = [line for line in current if line != EXPECTED_LINE]
    if orig_without_marker != current_without_replacement:
        return False, "unrelated lines were modified"

    return True, "ok"


if __name__ == "__main__":
    ok, reason = check(Path(sys.argv[1]))
    if ok:
        print("PASS")
        sys.exit(0)
    print(f"FAIL: {reason}")
    sys.exit(1)
