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
