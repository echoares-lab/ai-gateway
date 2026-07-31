from pathlib import Path

from scripts.ops.validate_exception_inventory import collect_handlers, load_contract, validate_inventory

ROOT = Path(__file__).resolve().parents[1]


def test_every_gateway_broad_handler_has_a_classification_rule() -> None:
    handlers = collect_handlers(ROOT / "services" / "gateway-engine")
    contract = load_contract(ROOT / "docs" / "EXCEPTION_BOUNDARY_CONTRACT.yaml")

    errors = validate_inventory(handlers, contract)

    assert errors == []
    assert len(handlers) > 100


def test_new_source_without_a_rule_fails_closed() -> None:
    handlers = collect_handlers(ROOT / "services" / "gateway-engine")
    contract = load_contract(ROOT / "docs" / "EXCEPTION_BOUNDARY_CONTRACT.yaml")
    handlers.append({"source": "services/gateway-engine/new_hotspot.py", "line": 1})

    assert validate_inventory(handlers, contract) == [
        "services/gateway-engine/new_hotspot.py:1 has no exception-boundary classification"
    ]
