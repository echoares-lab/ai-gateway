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
| `openapi/gateway-engine.yaml` | as above; also asserted by `services/gateway-engine/test_gateway_engine_client_config_contract.py` |
| `openapi/litellm.yaml` | as above |
| `openapi/policy-engine.yaml` | as above |

Removing or renaming any file under `openapi/` changes what the deployed
`docs-server` publishes.

## Machine-read contract files

| Path | Consumer |
| --- | --- |
| `ADMIN_ENDPOINT_EXPOSURE.yaml` | `scripts/ops/validate_admin_exposure.py` (default `--contract`), `make validate-admin-exposure` |
| `EXCEPTION_BOUNDARY_CONTRACT.yaml` | `scripts/ops/validate_exception_inventory.py` (default `--contract`), `make validate-exception-inventory` |
| `CICD_PHASE2_STAGING.md` | `tests/test-openbao-policy-denial-classifier.sh` extracts and `eval`s shell functions from this file and greps three exact configuration lines out of it |
| `CLIENT_CONFIG_GENERATION_CONTRACT.md` | `services/gateway-engine/test_gateway_engine_client_config_contract.py` |
| `CODEX_WEBSOCKET_TRANSLATION_CONTRACT.md` | `services/gateway-engine/test_gateway_engine_codex_ws_translation_contract.py` |
| `UNIFIED_CONFIG_ADMIN_API_CONTRACT.md` | `services/gateway-engine/test_gateway_engine_unified_config_contract.py` |
| `ops/RUNBOOK.md` | `tests/test_gemini_cli_routing_retirement.py` asserts retired Gemini CLI OAuth instructions are absent |

The four `.md` files above are pending a decision: either the assertions move to a
repo-local fixture and the prose moves to the vault, or the files stay here as
test fixtures. Until that is resolved they remain in the repository so the test
suite keeps passing. See `01 Projects/AI-Gateway/Todo.md`.

## `maestro/`

`maestro/.workspace-root` and `maestro/state/.gitignore` are Maestro tooling
markers, not documentation. The Maestro plan and state notes they accompanied
were migrated to `01 Projects/AI-Gateway/Specs/`.
