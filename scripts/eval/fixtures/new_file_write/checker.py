"""Checker for the new_file_write task."""
import importlib.util
import sys
from pathlib import Path


def check(scratch_dir: Path) -> tuple[bool, str]:
    target = scratch_dir / "utils" / "format_currency.py"
    if not target.exists():
        return False, "utils/format_currency.py was not created"

    spec = importlib.util.spec_from_file_location("format_currency_mod", target)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except Exception as e:  # noqa: BLE001
        return False, f"generated file failed to import: {e}"

    fn = getattr(module, "format_currency", None)
    if fn is None:
        return False, "format_currency function not defined"

    cases = {1050: "$10.50", 100000: "$1,000.00", 5: "$0.05", 0: "$0.00"}
    for cents, expected in cases.items():
        try:
            got = fn(cents)
        except Exception as e:  # noqa: BLE001
            return False, f"format_currency({cents}) raised {e}"
        if got != expected:
            return False, f"format_currency({cents}) == {got!r}, expected {expected!r}"

    return True, "ok"


if __name__ == "__main__":
    ok, reason = check(Path(sys.argv[1]))
    print("PASS" if ok else f"FAIL: {reason}")
    sys.exit(0 if ok else 1)
