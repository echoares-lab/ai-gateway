from pathlib import Path

import yaml


def _compose() -> dict:
    with Path("docker-compose.yml").open() as handle:
        return yaml.safe_load(handle)


def test_litellm_does_not_depend_on_standalone_prisma_migrate_job():
    services = _compose()["services"]

    assert "litellm-migrate" not in services

    litellm_depends_on = services["litellm"].get("depends_on", {})
    assert "litellm-migrate" not in litellm_depends_on


def test_litellm_healthcheck_allows_first_start_migration_recovery():
    healthcheck = _compose()["services"]["litellm"]["healthcheck"]

    assert healthcheck["start_period"] == "20m"
    assert healthcheck["retries"] >= 60
