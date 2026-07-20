# Tooling inventory: ai-gateway

## 1. Repository identity and status

- **Repository:** ai-gateway
- **Status:** active Python gateway and container stack
- **Git root:** `.`
- **Nested applications:** `services/gateway-engine`, credential-prober, docs-server, and mcp-postgres are documented here.

## 2. Runtime tools

| Tool | Version | Category | Required | Source | Purpose | Installation | Verification |
|---|---|---|---|---|---|---|---|
| Python | >=3.10 | Runtime | Required | `pyproject.toml` | Run gateway services and tests | Create a virtualenv; install project requirements | `python --version` |
| Docker | unversioned | Runtime | Required for stack | `docker-compose.yml` | Run service containers | Install Docker Engine | `docker version` |
| PostgreSQL | unversioned | Runtime | Required by stack | `docker-compose.yml` | Persist gateway data | Use Compose service | `docker compose ps` |

## 3. Project/build tools

| Tool | Version | Category | Required | Source | Purpose | Installation | Verification |
|---|---|---|---|---|---|---|---|
| setuptools | pyproject.toml | Project | Required | `pyproject.toml` | Package Python services | `python -m pip install -e .` | `python -m build` |
| Docker Compose | unversioned | Project | Required for local stack | `docker-compose.dev.yml` | Orchestrate local services | Install Compose plugin | `docker compose config` |
| Make | unversioned | Project | Optional | `Makefile` | Provide project tasks | Install make | `make help` |

## 4. Developer tools

| Tool | Version | Category | Required | Source | Purpose | Installation | Verification |
|---|---|---|---|---|---|---|---|
| pytest | requirements/pyproject | Dev | Required | `pyproject.toml` | Unit/integration tests | `pip install -e .` | `pytest -q` |
| shell scripts | unversioned | Dev | Required for selected workflows | `tests/test-gateway-e2e.sh` | Exercise gateway workflows | POSIX shell environment | `bash tests/test-gateway-e2e.sh` |

## 5. CI tools

| Tool | Version | Category | Required | Source | Purpose | Installation | Verification |
|---|---|---|---|---|---|---|---|
| GitHub Actions | unversioned | CI | CI-only | `.github/workflows/ci.yml` | Run tests and gates | GitHub-hosted | Workflow run |
| CycloneDX Python generator | unversioned | CI | CI-only | `.github/workflows/sbom.yml` | Generate Python dependency SBOM | Installed by workflow | `test -s ai-gateway-python.cdx.json` |

## 6. Operations/deployment tools

| Tool | Version | Category | Required | Source | Purpose | Installation | Verification |
|---|---|---|---|---|---|---|---|
| Kubernetes | unversioned | Ops | Operator-only | `docker-compose.cliproxy-build.yml` | Deploy promoted gateway images | Cluster/operator managed | Deployment health check |
| curl | unversioned | Ops | CI-only | `tests/test-gateway-e2e.sh` | Probe service endpoints | OS package | `curl --version` |

## 7. Native source manifests

- `pyproject.toml`, `requirements/*.txt`, and integration requirements define Python dependencies.
- Compose files and service Dockerfiles define container boundaries.
- Makefile, scripts, and GitHub workflows define project/CI tasks.

## 8. Standard commands

- `pip install -e .` — install gateway package (source: `pyproject.toml`).
- `pytest -q` — test suite (source: `.github/workflows/ci.yml`).
- `make` — repository tasks (source: `Makefile`).

## 9. Missing or unpinned tooling

- Python package versions are mixed: some are managed by `pyproject.toml`, others by requirements files.
- Docker, Compose, Kubernetes, and Make versions are unpinned.
- No single lockfile covers all Python services.

## 10. Future adoption notes

Evaluate `mise.toml` for Python, Docker/Compose, and task aliases; preserve native Python requirements and container manifests.

## SBOM artifact

`.github/workflows/sbom.yml` uploads `ai-gateway-python.cdx.json` as `ai-gateway-sbom`.
