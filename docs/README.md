# `docs/` — runtime and machine-verified artifacts only

This directory is **not** project documentation. Project documentation lives in
the Obsidian vault at `01 Projects/AI-Gateway/` (Master-Policy §1.6). Everything
that remains here is consumed by a running service or by an automated check, and
must not be moved out of the repository without updating the consumer.

## Published by the `docs-server` service

| Path | Consumer |
| --- | --- |
| `openapi/cliproxy.yaml` | `services/docs-server` — `COPY docs/openapi` in `services/docs-server/Dockerfile`, bind-mounted read-only at `./docs/openapi:/app/docs/openapi` in `docker-compose.yml`, and served on port `8002` (`8000` in-container) via Scalar. Also deployed to k3s as `nexus-docker.infra.plexplease.com/ai-gateway/docs-server`. |
| `openapi/cpa-manager.yaml` | as above |
| `openapi/gateway-engine.yaml` | as above |
| `openapi/litellm.yaml` | as above |
| `openapi/policy-engine.yaml` | as above |

Removing or renaming any file under `openapi/` changes what the deployed
`docs-server` publishes.

## Machine-read contract files

| Path | Consumer |
| --- | --- |
| `ADMIN_ENDPOINT_EXPOSURE.yaml` | `scripts/ops/validate_admin_exposure.py` (default `--contract`), `make validate-admin-exposure`; also cross-checked against the service contract by `services/gateway-engine/test_gateway_engine_client_config_contract.py` |
| `EXCEPTION_BOUNDARY_CONTRACT.yaml` | `scripts/ops/validate_exception_inventory.py` (default `--contract`), `make validate-exception-inventory` |

Both files are repo-wide inventories read by `scripts/ops/` validators, so they
stay here alongside the code they check.

No markdown in this directory is machine-read any more. The five prose files that
used to be asserted against were split on 2026-08-11: their machine-checked
substance became real fixtures in the repository, and their prose moved to the
vault.

| Former file | Fixture that replaced it | Prose now at |
| --- | --- | --- |
| `CLIENT_CONFIG_GENERATION_CONTRACT.md` | `services/gateway-engine/contracts/client_config_generation.yaml` | `Specs/CLIENT_CONFIG_GENERATION_CONTRACT.md` |
| `CODEX_WEBSOCKET_TRANSLATION_CONTRACT.md` | `services/gateway-engine/contracts/codex_ws_translation.yaml` | `Specs/CODEX_WEBSOCKET_TRANSLATION_CONTRACT.md` |
| `UNIFIED_CONFIG_ADMIN_API_CONTRACT.md` | `services/gateway-engine/contracts/unified_config_admin.yaml` | `Specs/UNIFIED_CONFIG_ADMIN_API_CONTRACT.md` |
| `CICD_PHASE2_STAGING.md` | `tests/lib/openbao-policy-denial-classifier.sh` | `Specs/CICD_PHASE2_STAGING.md` |
| `ops/RUNBOOK.md` | none needed — `tests/test_gemini_cli_routing_retirement.py` now scans every git-tracked file | `Runbooks/RUNBOOK.md` |

The three service contracts live in the **service tree**, not here, because the
gateway-engine unit-test image copies only `services/gateway-engine/`. While they
were markdown under `docs/`, every assertion against them silently skipped in
Gate A/B; as service-tree YAML they actually execute.

## `maestro/`

`maestro/.workspace-root` and `maestro/state/.gitignore` are Maestro tooling
markers, not documentation. The Maestro plan and state notes they accompanied
were migrated to `01 Projects/AI-Gateway/Specs/`.
