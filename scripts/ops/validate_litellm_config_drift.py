#!/usr/bin/env python3
"""Compare sanitized LiteLLM YAML model state with a Postgres metadata snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


def _model_map(config: dict[str, Any], source: str) -> dict[str, dict[str, Any]]:
    rows = config.get("model_list", []) if source == "yaml" else config.get("models", [])
    if not isinstance(rows, list):
        raise ValueError(f"{source} model list must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("model_name"), str):
            raise ValueError(f"{source} model rows require model_name")
        name = row["model_name"]
        if name in result:
            raise ValueError(f"duplicate {source} model: {name}")
        result[name] = row
    return result


def _diff_paths(left: Any, right: Any, prefix: str) -> list[str]:
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(_diff_paths(left[key], right[key], child))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        if left == right:
            return []
        return [prefix]
    return [] if left == right else [prefix]


def compare_configs(yaml_config: dict[str, Any], postgres_snapshot: dict[str, Any]) -> list[str]:
    """Return stable name/path-only drift messages.

    Postgres wins for an explicitly listed model setting override. All other
    model state must match the Git-tracked YAML. Non-model settings such as
    routing and MCP topology remain YAML-authoritative and are documented in
    ``01 Projects/AI-Gateway/Specs/CONFIG_PROMOTION.md``.
    """

    yaml_models = _model_map(yaml_config, "yaml")
    postgres_models = _model_map(postgres_snapshot, "postgres")
    overrides = {
        (item.get("model_name"), item.get("path"))
        for item in postgres_snapshot.get("intentional_overrides", [])
        if isinstance(item, dict)
    }
    errors: list[str] = []
    for name in sorted(set(yaml_models) | set(postgres_models)):
        if name not in postgres_models:
            errors.append(f"model_list[{name}] is missing from postgres")
            continue
        if name not in yaml_models:
            errors.append(f"model_list[{name}] exists only in postgres")
            continue
        yaml_params = yaml_models[name].get("litellm_params", {})
        postgres_params = postgres_models[name].get("litellm_params", {})
        for path in _diff_paths(yaml_params, postgres_params, "litellm_params"):
            if (name, path) not in overrides:
                errors.append(f"model_list[{name}].{path} differs")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("yaml_config", type=Path)
    parser.add_argument("postgres_snapshot", type=Path, help="sanitized JSON metadata; never production credentials")
    args = parser.parse_args()
    try:
        yaml_config = yaml.safe_load(args.yaml_config.read_text(encoding="utf-8"))
        postgres_snapshot = json.loads(args.postgres_snapshot.read_text(encoding="utf-8"))
        errors = compare_configs(yaml_config, postgres_snapshot)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(json.dumps({"status": "invalid-input", "error": str(exc)}, sort_keys=True))
        return 2
    report = {"drift": errors, "status": "drift" if errors else "clean"}
    print(json.dumps(report, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
