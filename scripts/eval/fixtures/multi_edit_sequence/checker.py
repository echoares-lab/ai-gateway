"""Checker for the multi_edit_sequence task."""

import sys
from pathlib import Path


def check(scratch_dir: Path) -> tuple[bool, str]:
    target = scratch_dir / "config.py"
    if not target.exists():
        return False, "config.py missing from scratch dir"

    try:
        ns: dict = {}
        exec(compile(target.read_text(), "config.py", "exec"), ns)
    except Exception as e:  # noqa: BLE001
        return False, f"config.py failed to exec: {e}"

    expected = {
        "MAX_RETRIES": 7,
        "TIMEOUT_SECONDS": 45,
        "FEATURE_FLAG_NEW_UI": True,
        "LOG_LEVEL": "INFO",
        "DEFAULT_LOCALE": "en-US",
    }
    for key, want in expected.items():
        got = ns.get(key)
        if got != want:
            return False, f"{key} == {got!r}, expected {want!r}"

    return True, "ok"


if __name__ == "__main__":
    ok, reason = check(Path(sys.argv[1]))
    print("PASS" if ok else f"FAIL: {reason}")
    sys.exit(0 if ok else 1)
