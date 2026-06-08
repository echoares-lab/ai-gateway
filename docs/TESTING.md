# Testing Guide — AI Gateway

How to run tests, choose the right gate, and mock external dependencies without flakiness.

See also: [`TESTING_AND_PROMOTION_POLICY.md`](../TESTING_AND_PROMOTION_POLICY.md), [`REPO_IMPROVEMENT_APPENDIX.md`](../REPO_IMPROVEMENT_APPENDIX.md), [`CI_SELF_HOSTED.md`](CI_SELF_HOSTED.md).

---

## Gate overview

| Gate | Local command | Stack | When |
|------|---------------|-------|------|
| **A** | `make lint` / `make test-unit` | Gateway Engine Docker only | Every change |
| **B** | `make test-mock` | Mock stack slot 9 → `:4090` | Runtime / integration changes |
| **C** | `make test-e2e` or PR label `run-e2e` | Real OAuth slot 1 → `:4010` | Hotspot paths or high-risk |
| **D** | `./cliproxy-setup.sh test <model>` | Stable `:4000` | Post-merge on `main` |

Fast pre-push loop: `make test-fast` (Gate A + B locally).

---

## Environment slots and ports

| Slot | Gateway Engine | LiteLLM UI | cliproxy | policy-engine | Purpose |
|------|------------|------------|----------|---------------|---------|
| 0 | `:4000` | `:4001` | `:8317` | `:8080` | **Stable — never use for feature work** |
| 1 | `:4010` | `:4011` | `:8327` | `:18080` | Real OAuth dev (Gate C) |
| 2 | `:4020` | `:4021` | `:8337` | `:18090` | Additional dev slot |
| 9 | `:4090` | `:4091` | `:8397` | `:18160` | Mock stack (Gate B) |

CI mock-integration binds slot-1 ports (`:4010`, `:4011`, `:18080`) on the self-hosted runner.

---

## Unit tests (Gate A)

```bash
make test-unit
# Same as CI: docker build + pytest -n auto inside the gateway-engine image
```

### Parallelization

CI and local `make test-unit` both use **pytest-xdist** (`-n auto`) for gateway-engine tests. Integration tests run **serially** against a single `GATEWAY_URL` — do not add xdist there without port isolation.

### Mocking patterns

| Dependency | Approach | Example |
|------------|----------|---------|
| **Redis** | `fakeredis.FakeRedis` via `conftest.py` fixtures | Rate-limit / affinity tests |
| **HTTP upstream (httpx)** | `respx` mock router (preferred) or `patch.object` on `main._client` | Policy-engine / LiteLLM calls |
| **FastAPI routes** | `TestClient` + env `monkeypatch` | Admin / chat completion handlers |
| **Postgres** | `MagicMock` cursors in unit tests; real Postgres only in Gate B+ | `test_profile_store.py` |
| **Inventory / profiles** | In-memory `fixtures={}` on `InventoryStore` | No DB in unit tier |
| **Prometheus counters** | `patch.object` on `.labels()` | Token analytics tests |

Shared fixtures live in [`services/gateway-engine/conftest.py`](../services/gateway-engine/conftest.py).

### When to use unit mocks vs mock stack

- **Unit mocks (Gate A):** Pure logic, single-service behavior, HTTP client patching, Redis state. Fast, no Docker compose.
- **Mock stack (Gate B):** End-to-end wire format, gateway-engine + LiteLLM + mock cliproxy + mock policy-engine. Required for integration tests under `tests/integration/`.

---

## Integration tests (Gate B)

```bash
make test-mock   # starts slot 9, runs pytest -m mock, tears down
# Or manually:
./dev-env.sh start-mock 9
GATEWAY_URL=http://localhost:4090 ALLOW_MODEL_SKIP=0 \
  pytest tests/integration/ -m mock -v
./dev-env.sh stop-mock 9
```

Mock tier sets `ALLOW_MODEL_SKIP=0` so HTTP 400/404/503 are hard failures (not skips).

### DB isolation

- **CI:** Set `CI_MOCK_FRESH_DB=1` (or `CI_MOCK_DOWN_VOLUMES=1`) to drop the `aidevmock` Postgres volume between runs.
- **Within a run:** `tests/integration/conftest.py` resets mock policy-engine state via `POST /v1/debug/reset` before each test.

---

## Policy-engine unit tests

```bash
cd services/policy-engine
python3 -m venv .venv && .venv/bin/pip install -r requirements-test.txt
PYTHONPATH=. .venv/bin/pytest test_*.py -v
```

Also run via `make test-unit` (includes policy-engine when wired).

---

## Real-provider E2E (Gate C)

Requires OAuth tokens in `~/.cli-proxy-api/` (dev stacks seed an isolated copy — never write back to host auth files from dev stacks).

```bash
make test-e2e
# Or: ./dev-env.sh start 1 && ./dev-env.sh test 1 -- -m "integration and smoke"
```

Gate C is opt-in in CI: add the `run-e2e` PR label or run `workflow_dispatch` on the CI workflow. Hotspot paths no longer auto-trigger `real-provider-e2e` (pending e2e refactor).

---

## Lint and schema

```bash
make lint
make validate-policy-profiles
```

---

## CI parity notes

| Check | Local | CI |
|-------|-------|-----|
| Unit tests | `make test-unit` (`-n auto`) | `unit-tests` job |
| Mock integration | `make test-mock` | `mock-integration` (path-filtered) |
| Multi-repo isolation | `bash tests/test-multi-repo-isolation.sh` | `multi-repo-isolation` (path-filtered) |
| `make test-fast` | lint + unit + policy validation + mock | Does **not** run isolation — run isolation script when touching `dev-env.sh`, `cliproxy-setup.sh`, etc. |
