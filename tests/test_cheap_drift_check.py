import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "policy" / "cheap_drift_check.py"


def _write_litellm_config(path: Path, model_names: list[str]) -> None:
    lines = ["model_list:"]
    for model_name in model_names:
        lines.extend(
            [
                f"  - model_name: {model_name}",
                "    litellm_params:",
                f"      model: openai/{model_name}",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_model_registry(path: Path, model_ids: list[str]) -> None:
    lines = ["models:"]
    for model_id in model_ids:
        lines.append(f"  - model_id: {model_id}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_catalog(path: Path, model_ids: list[str]) -> None:
    payload = {"data": [{"id": model_id} for model_id in model_ids]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run_checker(
    litellm_config: Path,
    model_registry: Path,
    catalog_file: Path,
    *,
    threshold: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--litellm-config",
            str(litellm_config),
            "--model-registry",
            str(model_registry),
            "--catalog-file",
            str(catalog_file),
            "--threshold",
            str(threshold),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def test_no_drift_exits_zero(tmp_path: Path) -> None:
    litellm_config = tmp_path / "litellm-config.yaml"
    model_registry = tmp_path / "model-registry.yaml"
    catalog_file = tmp_path / "catalog.json"

    _write_litellm_config(litellm_config, ["alpha", "beta"])
    _write_model_registry(model_registry, [])
    _write_catalog(catalog_file, ["alpha", "beta"])

    result = _run_checker(litellm_config, model_registry, catalog_file, threshold=0)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["configured_not_served"] == []
    assert report["served_not_configured"] == []
    assert report["total_drift_count"] == 0
    assert report["within_threshold"] is True


def test_drift_over_threshold_exits_non_zero(tmp_path: Path) -> None:
    litellm_config = tmp_path / "litellm-config.yaml"
    model_registry = tmp_path / "model-registry.yaml"
    catalog_file = tmp_path / "catalog.json"

    _write_litellm_config(litellm_config, ["alpha", "beta"])
    _write_model_registry(model_registry, [])
    _write_catalog(catalog_file, ["alpha", "gamma"])

    result = _run_checker(litellm_config, model_registry, catalog_file, threshold=1)

    assert result.returncode != 0
    report = json.loads(result.stdout)
    assert report["configured_not_served"] == ["beta"]
    assert report["served_not_configured"] == ["gamma"]
    assert report["total_drift_count"] == 2
    assert report["within_threshold"] is False


def test_offline_catalog_file_parsing_and_normalization(tmp_path: Path) -> None:
    litellm_config = tmp_path / "litellm-config.yaml"
    model_registry = tmp_path / "model-registry.yaml"
    catalog_file = tmp_path / "catalog.json"

    _write_litellm_config(litellm_config, ["gpt-5-4"])
    _write_model_registry(model_registry, ["registry-only"])
    _write_catalog(catalog_file, ["gpt-5.4", "registry-only"])

    result = _run_checker(litellm_config, model_registry, catalog_file, threshold=0)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["sources"]["catalog"].startswith("file:")
    assert report["configured_not_served"] == []
    assert report["served_not_configured"] == []
    assert report["total_drift_count"] == 0
