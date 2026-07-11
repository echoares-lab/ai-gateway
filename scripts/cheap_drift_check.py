#!/usr/bin/env python3
"""Cheap model-catalog drift detector based on set membership only."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml


def normalize_model_id(value: str) -> str:
    normalized = value.strip().lower()
    return normalized.replace(".", "-")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping at {path}, got {type(data).__name__}")
    return data


def load_litellm_aliases(path: Path) -> set[str]:
    data = _load_yaml(path)
    model_list = data.get("model_list", [])
    if not isinstance(model_list, list):
        raise ValueError(f"Expected model_list to be a list in {path}")
    aliases: set[str] = set()
    for item in model_list:
        if not isinstance(item, dict):
            continue
        name = item.get("model_name")
        if isinstance(name, str) and name.strip():
            aliases.add(normalize_model_id(name))
    return aliases


def load_registry_aliases(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = _load_yaml(path)
    models = data.get("models", [])
    if not isinstance(models, list):
        raise ValueError(f"Expected models to be a list in {path}")
    aliases: set[str] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        for key in ("model_id", "model_name", "alias"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                aliases.add(normalize_model_id(value))
    return aliases


def _parse_openai_catalog(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        raise ValueError("Catalog payload must be a JSON object")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Catalog payload must include data as a list")

    catalog: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if isinstance(model_id, str) and model_id.strip():
            catalog.add(normalize_model_id(model_id))
    return catalog


def load_catalog_from_file(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return _parse_openai_catalog(payload)


def fetch_catalog_from_cliproxy(cliproxy_url: str, api_key: str, timeout_seconds: int = 10) -> set[str]:
    if not api_key:
        raise ValueError("CLIPROXY_API_KEY must be set unless --catalog-file is used")

    base = cliproxy_url.rstrip("/")
    request = urllib.request.Request(f"{base}/v1/models")
    request.add_header("Authorization", f"Bearer {api_key}")
    request.add_header("Accept", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"CLIProxy returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach CLIProxy: {exc.reason}") from exc

    return _parse_openai_catalog(payload)


def build_report(
    configured: set[str],
    served: set[str],
    *,
    threshold: int,
    litellm_config_path: Path,
    model_registry_path: Path,
    catalog_source: str,
) -> dict[str, Any]:
    configured_not_served = sorted(configured - served)
    served_not_configured = sorted(served - configured)
    total_drift_count = len(configured_not_served) + len(served_not_configured)

    return {
        "configured_count": len(configured),
        "served_count": len(served),
        "configured_not_served": configured_not_served,
        "served_not_configured": served_not_configured,
        "total_drift_count": total_drift_count,
        "threshold": threshold,
        "within_threshold": total_drift_count <= threshold,
        "sources": {
            "litellm_config": str(litellm_config_path),
            "model_registry": str(model_registry_path),
            "catalog": catalog_source,
        },
        "normalization": "lowercase + replace '.' with '-'",
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect model catalog drift by set membership only (no probe calls)."
    )
    parser.add_argument(
        "--litellm-config",
        default="litellm-config.yaml",
        help="Path to LiteLLM config containing model_list[].model_name",
    )
    parser.add_argument(
        "--model-registry",
        default="config/model-registry.yaml",
        help="Optional model registry path; ignored when missing",
    )
    parser.add_argument(
        "--catalog-file",
        help="Offline JSON file in OpenAI /v1/models format: {\"data\":[{\"id\":\"...\"}]}",
    )
    parser.add_argument(
        "--cliproxy-url",
        default=os.environ.get("CLIPROXY_URL", "http://localhost:8317"),
        help="CLIProxy base URL (used only when --catalog-file is not set)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=0,
        help="Fail when total drift count is greater than this threshold",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.threshold < 0:
        raise ValueError("--threshold must be >= 0")

    litellm_path = Path(args.litellm_config)
    registry_path = Path(args.model_registry)
    catalog_file_path = Path(args.catalog_file) if args.catalog_file else None

    configured = load_litellm_aliases(litellm_path)
    configured |= load_registry_aliases(registry_path)

    if catalog_file_path is not None:
        served = load_catalog_from_file(catalog_file_path)
        catalog_source = f"file:{catalog_file_path}"
    else:
        api_key = os.environ.get("CLIPROXY_API_KEY", "")
        served = fetch_catalog_from_cliproxy(args.cliproxy_url, api_key)
        catalog_source = f"http:{args.cliproxy_url.rstrip('/')}/v1/models"

    report = build_report(
        configured,
        served,
        threshold=args.threshold,
        litellm_config_path=litellm_path,
        model_registry_path=registry_path,
        catalog_source=catalog_source,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["within_threshold"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as exc:
        error_report = {
            "error": str(exc),
            "type": exc.__class__.__name__,
        }
        print(json.dumps(error_report, indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(2)
