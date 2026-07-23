from pathlib import Path

import pytest
import yaml


def _compose() -> dict:
    with Path("docker-compose.yml").open() as handle:
        return yaml.safe_load(handle)


def _compose_file(name: str) -> dict:
    with Path(name).open() as handle:
        return yaml.safe_load(handle)


def _volume_target(service: dict, target: str) -> str | None:
    for volume in service.get("volumes", []):
        source, mounted_at, *_options = volume.split(":")
        if mounted_at == target:
            return source
    return None


def _environment_value(service: dict, name: str) -> str | None:
    environment = service.get("environment", {})
    if isinstance(environment, dict):
        return environment.get(name)
    prefix = f"{name}="
    return next((item.removeprefix(prefix) for item in environment if item.startswith(prefix)), None)


def test_litellm_does_not_depend_on_standalone_prisma_migrate_job():
    services = _compose()["services"]

    assert "litellm-migrate" not in services

    litellm_depends_on = services["litellm"].get("depends_on", {})
    assert "litellm-migrate" not in litellm_depends_on


def test_litellm_healthcheck_allows_first_start_migration_recovery():
    healthcheck = _compose()["services"]["litellm"]["healthcheck"]

    assert healthcheck["start_period"] == "20m"
    assert healthcheck["retries"] >= 60


@pytest.mark.parametrize("compose_name", ["docker-compose.yml", "docker-compose.dev.yml"])
def test_reconciliation_uses_shared_writable_litellm_artifact(compose_name):
    compose = _compose_file(compose_name)
    services = compose["services"]
    shared_volume = "litellm_reconciliation_artifacts"

    assert shared_volume in compose["volumes"]
    assert _volume_target(services["gateway-engine"], "/config") == shared_volume
    assert _volume_target(services["litellm"], "/config") == shared_volume
    assert _environment_value(services["gateway-engine"], "LITELLM_CONFIG_PATH") == "/config/litellm-config.yaml"
    assert services["litellm"]["command"][:2] == ["--config", "/config/litellm-config.yaml"]

    initializer = services["litellm-config-init"]
    assert _volume_target(initializer, "/config") == shared_volume
    assert _volume_target(initializer, "/seed/litellm-config.yaml") == "./litellm-config.yaml"
    assert services["litellm"]["depends_on"]["litellm-config-init"]["condition"] == "service_completed_successfully"
