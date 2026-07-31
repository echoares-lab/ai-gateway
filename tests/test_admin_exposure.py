from pathlib import Path

from scripts.ops.validate_admin_exposure import (
    collect_sensitive_routes,
    load_contract,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def test_documented_contract_covers_every_sensitive_route() -> None:
    routes = collect_sensitive_routes(ROOT / "services" / "gateway-engine")
    contract = load_contract(ROOT / "docs" / "ADMIN_ENDPOINT_EXPOSURE.yaml")

    assert validate_contract(routes, contract) == []


def test_new_admin_route_is_reported_as_unclassified() -> None:
    routes = collect_sensitive_routes(ROOT / "services" / "gateway-engine")
    contract = load_contract(ROOT / "docs" / "ADMIN_ENDPOINT_EXPOSURE.yaml")
    routes.add(("GET", "/admin/new-unclassified"))

    errors = validate_contract(routes, contract)

    assert errors == ["GET /admin/new-unclassified is not classified"]


def test_contract_rejects_duplicate_route_entries() -> None:
    contract = load_contract(ROOT / "docs" / "ADMIN_ENDPOINT_EXPOSURE.yaml")
    contract.append(contract[0].copy())

    errors = validate_contract(collect_sensitive_routes(ROOT / "services" / "gateway-engine"), contract)

    assert errors == [f"duplicate contract entry: {contract[0]['method']} {contract[0]['path']}"]
