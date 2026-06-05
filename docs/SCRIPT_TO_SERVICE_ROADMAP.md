# API Evolution: Script-to-Service Roadmap

This document identifies local scripts that are prime candidates for future transformation into formal API services.

## Candidate Scripts
- **`cliproxy-setup.sh`**: Currently handles complex proxy setup and login flows.
    - *Evolution Path*: Move logic into a `cliproxy-management` API service to handle remote auth-file management, session login, and health monitoring.
- **`gen-client-config.sh`**: Generates client-specific configurations.
    - *Evolution Path*: Expose as an endpoint `/v1/config/generate` to dynamically generate configurations based on client requests, reducing the need for local shell scripts.
- **`setup_litellm_teams.py`**: Manages team configurations and keys.
    - *Evolution Path*: Formalize into a `team-manager` API that exposes CRUD endpoints for teams, workspaces, and virtual keys.

## Architectural Transition Plan
1. **Abstraction**: Extract business logic from shell scripts into reusable Python modules or classes.
2. **Endpoint Mapping**: Define FastAPI or similar endpoints corresponding to the current script operations.
3. **Formalization**: Once functional parity is achieved, deprecate the manual script usage in favor of API-driven workflows.
