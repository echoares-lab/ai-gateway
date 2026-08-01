#!/usr/bin/env python3
"""Check that gateway administrative/operational routes have exposure policy."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
from typing import Any

import yaml

EXPOSURE_CLASSES = {
    "public-edge-waf",
    "internal-ingress",
    "cluster-internal",
    "operator-local",
}


def _constant_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _methods(node: ast.Call, decorator: str) -> list[str]:
    if decorator == "api_route":
        for keyword in node.keywords:
            if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                return [item.value for item in keyword.value.elts if isinstance(item, ast.Constant)]
        return []
    return [decorator.upper()]


def collect_sensitive_routes(service_root: Path) -> set[tuple[str, str]]:
    """Collect route declarations that require an exposure decision.

    Catch-all proxy routes and ordinary public model routes are intentionally
    excluded. Any new `/admin`, `/debug`, `/model`, probe, or operational route
    is included automatically and must be added to the YAML contract.
    """

    routes: set[tuple[str, str]] = set()
    for path in service_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator_node in node.decorator_list:
                if not isinstance(decorator_node, ast.Call):
                    continue
                if not isinstance(decorator_node.func, ast.Attribute):
                    continue
                decorator = decorator_node.func.attr
                if decorator not in {"get", "post", "put", "patch", "delete", "websocket", "api_route"}:
                    continue
                if not decorator_node.args:
                    continue
                route = _constant_string(decorator_node.args[0])
                if route is None:
                    continue
                if not (
                    route.startswith(("/admin", "/debug", "/model"))
                    or route
                    in {
                        "/metrics",
                        "/health",
                        "/health/ready",
                        "/version",
                        "/v1/events/credential",
                        "/v1/config/generate",
                    }
                ):
                    continue
                for method in _methods(decorator_node, decorator):
                    routes.add((method.upper(), route))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "add_api_route" or not node.args:
                continue
            route = _constant_string(node.args[0])
            if route and route != "/{path:path}" and route.startswith(("/admin", "/debug", "/model")):
                routes.update((method, route) for method in _methods(node, "api_route"))
    return routes


def load_contract(path: Path) -> list[dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("routes"), list):
        raise ValueError("contract must contain a routes list")
    return document["routes"]


def validate_contract(routes: set[tuple[str, str]], contract: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for entry in contract:
        if not isinstance(entry, dict):
            errors.append("contract entry must be a mapping")
            continue
        method = entry.get("method")
        path = entry.get("path")
        key = (method, path)
        if key in seen:
            errors.append(f"duplicate contract entry: {method} {path}")
        seen.add(key)
        missing = [
            field for field in ("method", "path", "source", "exposure", "auth", "boundary") if not entry.get(field)
        ]
        if missing:
            errors.append(f"{method} {path} missing fields: {', '.join(missing)}")
        if entry.get("exposure") not in EXPOSURE_CLASSES:
            errors.append(f"{method} {path} has invalid exposure class")
    for method, path in sorted(routes - seen):
        errors.append(f"{method} {path} is not classified")
    for method, path in sorted(seen - routes):
        errors.append(f"{method} {path} is documented but not declared")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-root", type=Path, default=Path("services/gateway-engine"))
    parser.add_argument("--contract", type=Path, default=Path("docs/ADMIN_ENDPOINT_EXPOSURE.yaml"))
    args = parser.parse_args()
    try:
        errors = validate_contract(collect_sensitive_routes(args.service_root), load_contract(args.contract))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"admin exposure contract error: {exc}")
        return 2
    if errors:
        print("Admin exposure contract failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Admin exposure contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
