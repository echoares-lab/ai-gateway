# API Documentation System

This repository uses an automated, containerized documentation system based on [Scalar](https://scalar.com/).

## Accessing Documentation
The documentation site is hosted within the Docker environment and can be accessed at:
**`http://localhost:8002`**

The index lists every OpenAPI spec mounted from `docs/openapi/`. Direct links:
- **Gateway Engine API**: `http://localhost:8002/docs/gateway-engine.yaml`
- **CLIProxy API**: `http://localhost:8002/docs/cliproxy.yaml`
- **LiteLLM API**: `http://localhost:8002/docs/litellm.yaml`
- **CPA Manager API**: `http://localhost:8002/docs/cpa-manager.yaml`

Gateway runtime model mutation endpoints (`POST /model/new`, `POST /model/delete`) are documented in `docs/openapi/gateway-engine.yaml`.

### Production quota status

`GET /admin/quota/status` combines CLIProxy passive quota state, a live
full-window refresh, and credential metadata into per-account quota windows.
Query the production Gateway Engine directly:

```bash
curl -fsS https://gateway.infra.plexplease.com/admin/quota/status
```

If admin read authentication is enabled, send the Gateway Engine admin key:

```bash
curl -fsS \
  -H "x-admin-key: $GATEWAY_ENGINE_ADMIN_KEY" \
  https://gateway.infra.plexplease.com/admin/quota/status
```

For a compact operator-facing summary, use the repository helper:

```bash
GATEWAY_ENGINE_URL=https://gateway.infra.plexplease.com \
  ./cliproxy-setup.sh quota-summary
```

The helper also reads `GATEWAY_ENGINE_ADMIN_KEY` from the environment or
`.env` and sends it when present. Because the endpoint performs a live provider
refresh, allow up to 30 seconds for a response before treating the request as
timed out.

### Historical / Internal Specifications

- **Policy Engine API**: `http://localhost:8002/docs/policy-engine.yaml` is
  retained as a historical schema reference for policy decisions and profile
  shapes. The standalone policy-engine service is decommissioned, so the spec
  intentionally does not advertise a live `servers:` target. Use the Gateway
  Engine admin status API for runtime policy trace data.

## Adding New Endpoints
1. **Define Specification**: Add or update the corresponding OpenAPI YAML file in `docs/openapi/`.
2. **Add Examples**: Enrich the YAML with `example` objects for both request bodies and responses to enable "Try it out" functionality.
3. **Automatic Update**: Since the `docs/openapi/` folder is mounted as a volume, your changes will be reflected immediately at `http://localhost:8002` without requiring a container rebuild.

## Infrastructure
- **Server**: A lightweight FastAPI app in `services/docs-server/` serves the Scalar UI.
- **Dockerization**: The server is included in `docker-compose.yml` under the `docs-server` service.
