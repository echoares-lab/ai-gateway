#!/usr/bin/env python3
"""Inventory broad gateway exception handlers and enforce a classification rule."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

import yaml


def _catches_exception(node: ast.ExceptHandler) -> bool:
    if node.type is None:
        return True
    if isinstance(node.type, ast.Name):
        return node.type.id in {"Exception", "BaseException"}
    if isinstance(node.type, ast.Tuple):
        return any(isinstance(item, ast.Name) and item.id in {"Exception", "BaseException"} for item in node.type.elts)
    return False


def collect_handlers(service_root: Path) -> list[dict[str, Any]]:
    handlers: list[dict[str, Any]] = []
    for path in sorted(service_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and _catches_exception(node):
                handlers.append(
                    {"source": path.relative_to(service_root.parent.parent).as_posix(), "line": node.lineno}
                )
    return sorted(handlers, key=lambda item: (item["source"], item["line"]))


def load_contract(path: Path) -> list[dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("rules"), list):
        raise ValueError("contract must contain a rules list")
    return document["rules"]


def validate_inventory(handlers: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for rule in rules:
        required = ("prefix", "classification", "caller_contract", "risk")
        missing = [field for field in required if not rule.get(field)]
        if missing:
            errors.append(f"rule missing fields: {', '.join(missing)}")
    for handler in handlers:
        source = handler.get("source", "")
        if not any(source.startswith(str(rule.get("prefix", ""))) for rule in rules):
            errors.append(f"{source}:{handler.get('line')} has no exception-boundary classification")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-root", type=Path, default=Path("services/gateway-engine"))
    parser.add_argument("--contract", type=Path, default=Path("docs/EXCEPTION_BOUNDARY_CONTRACT.yaml"))
    args = parser.parse_args()
    try:
        handlers = collect_handlers(args.service_root)
        rules = load_contract(args.contract)
        errors = validate_inventory(handlers, rules)
    except (OSError, ValueError, SyntaxError, yaml.YAMLError) as exc:
        print(json.dumps({"status": "invalid-input", "error": str(exc)}, sort_keys=True))
        return 2
    report = {"errors": errors, "handlers": handlers, "status": "invalid" if errors else "clean"}
    print(json.dumps(report, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
