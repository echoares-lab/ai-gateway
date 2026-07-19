"""Checker for the near_duplicate_edit task."""
import sys
from pathlib import Path


def check(scratch_dir: Path) -> tuple[bool, str]:
    target = scratch_dir / "handlers.py"
    if not target.exists():
        return False, "handlers.py missing from scratch dir"

    src = target.read_text()

    try:
        ns: dict = {}
        exec(compile(src, "handlers.py", "exec"), ns)
    except Exception as e:  # noqa: BLE001
        return False, f"handlers.py failed to exec: {e}"

    invoice = ns["InvoiceHandler"]("a").process(10)
    order = ns["OrderHandler"]("b").process(10)
    shipment = ns["ShipmentHandler"]("c").process(10)

    if order != 110:
        return False, f"OrderHandler.process(10) == {order}, expected 110"
    if invoice != 11:
        return False, f"InvoiceHandler.process(10) == {invoice}, expected 11 (should be unchanged)"
    if shipment != 11:
        return False, f"ShipmentHandler.process(10) == {shipment}, expected 11 (should be unchanged)"

    return True, "ok"


if __name__ == "__main__":
    ok, reason = check(Path(sys.argv[1]))
    print("PASS" if ok else f"FAIL: {reason}")
    sys.exit(0 if ok else 1)
