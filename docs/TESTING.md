# Testing Guide — AI Gateway

How to run tests, choose the right gate, and mock external dependencies without flakiness.

See also: [`docs/process/TESTING_AND_PROMOTION_POLICY.md`](process/TESTING_AND_PROMOTION_POLICY.md), [`docs/process/REPO_IMPROVEMENT_APPENDIX.md`](process/REPO_IMPROVEMENT_APPENDIX.md), [`CI_SELF_HOSTED.md`](CI_SELF_HOSTED.md), [`docs/ops/DEPENDENCY_UPDATES.md`](ops/DEPENDENCY_UPDATES.md) (per-component gates and promote path for third-party images).

---

## Gate overview

| Gate | Local command | Stack | When |
|------|---------------|-------|------|
| **A** | `make lint` / `make test-unit` | Gateway Engine Docker image only | Every change |
| **B** | `make test-mock` | In-memory ASGI (no compose, no OAuth) | Runtime / integration changes |
| **C** | `make test-e2e` or PR label `run-e2e` | Real OAuth slot 1 → `:4010` | High-risk / when opted in |
| **D** | `./cliproxy-setup.sh test <model>` | Stable `:4000` (or k8s prod edge) | Post-merge on `main` (thin) |
| **Deep smoke** | `./scripts/ops/deep-smoke.sh --env staging --full` | Staging k8s (`ai-gateway-staging`) | **Promote gate** before prod digest pin |

Fast pre-push loop: `make test-fast` (Gate A + B locally).

**Gate C policy (encoded once):** CI `real-provider-e2e` is **opt-in only** (`run-e2e` label or `workflow_dispatch`). It is **not** required to merge. Hotspot path auto-trigger is paused. Use Gate C for high-risk auth/config/compose/cliproxy changes; nightly + post-merge Gate D cover the rest.

**Gate D vs deep smoke:** Gate D is a **thin** post-merge advisory smoke (health + a few model
completions on stable `:4000` or prod k8s edge). **Deep smoke `--full`** is the **staging promote
gate** (epic [#396](https://github.com/echoares-lab/ai-gateway/issues/396)) — multi-API shapes,
streaming, admin surfaces, cluster/DB checks — and must pass **before** opening the k3s-01
digest-pin PR. It is **CI-enforced** by `promote-k3s-images.yml` → `staging-deep-smoke.yml`
(issue #410); local operator runs remain supported. Not required on every merge to `main`
outside the promote path. Langfuse checks are **warn-only** unless `--strict` is set. Quota is
**OpenAPI-hardened** (issue #403): required top-level/account fields and `live_status` enums —
see [`docs/openapi/gateway-engine.yaml`](openapi/gateway-engine.yaml) and
[`docs/superpowers/specs/2026-07-17-staging-deep-smoke-design.md`](superpowers/specs/2026-07-17-staging-deep-smoke-design.md).

---

## Environment slots and ports

| Slot | Gateway Engine | LiteLLM UI | cliproxy | Purpose |
|------|------------|------------|----------|---------|
| 0 | `:4000` | `:4001` | `:8317` | **Stable — never use for feature work** |
| 1 | `:4010` | `:4011` | `:8327` | Real OAuth dev (Gate C) |
| 2 | `:4020` | `:4021` | `:8337` | Additional dev slot |
| 3+ | `4000+N*10` | `4001+N*10` | `8317+N*10` | Additional isolated dev slots |

Policy evaluation runs **in-process** inside gateway-engine (`services/gateway-engine/core/policy/`). There is no separate `policy-engine` service or port.

Gate B does **not** use a compose mock slot. Prefer `make test-mock` (in-memory ASGI + respx + fakeredis).

---

## Unit tests (Gate A)

```bash
make test-unit
# Same as CI: docker build + pytest -n auto inside the gateway-engine image
```

Unit tests live under `services/gateway-engine/test_gateway_engine*.py` (underscore, not hyphen).

### Parallelization

CI and local `make test-unit` both use **pytest-xdist** (`-n auto`) for gateway-engine tests. Integration tests run **serially** against a single app — do not add xdist there without isolation.

### Mocking patterns

| Dependency | Approach | Example |
|------------|----------|---------|
| **Redis** | `fakeredis.FakeRedis` via `conftest.py` fixtures | Rate-limit / affinity tests |
| **HTTP upstream (httpx)** | `respx` mock router (preferred) or `patch` on the module under test | LiteLLM / CLIProxy calls |
| **FastAPI routes** | `TestClient` + env `monkeypatch` | Admin / chat completion handlers |
| **Postgres** | `MagicMock` cursors in unit tests; real Postgres only in compose stacks | `test_profile_store.py` |
| **Inventory / profiles** | In-memory `fixtures={}` on `InventoryStore` | No DB in unit tier |
| **Prometheus counters** | `patch.object` on `.labels()` | Token analytics tests |

Shared fixtures live in [`services/gateway-engine/conftest.py`](../services/gateway-engine/conftest.py).

Policy logic is tested with the gateway-engine suite (`test_gateway_engine_policy*.py`, etc.) — there is no standalone `services/policy-engine/` tree.

### When to use unit mocks vs Gate B

- **Unit mocks (Gate A):** Pure logic, single-service behavior, HTTP client patching, Redis state. Fast, no Docker compose.
- **Gate B (`make test-mock`):** Wire-format / routing matrix via in-memory ASGI against canned upstreams. Required CI parity for runtime paths.

---

## Integration tests (Gate B)

```bash
make test-mock
# Equivalent:
python3 -m pytest tests/integration/ -m mock -v
```

Gate B is **in-memory ASGI** (see `tests/integration/conftest.py`). It does **not** start Docker compose or slot 9.

`./dev-env.sh start-mock` / `stop-mock` are **retired stubs** — they exit with an error directing you to `make test-mock`. Do not rely on a mock compose stack.

Mock tier sets `ALLOW_MODEL_SKIP=0` so HTTP 400/404/503 are hard failures (not skips) when those env vars apply.

---

## Real-provider E2E (Gate C)

Requires OAuth tokens in `~/.cli-proxy-api/` (dev stacks seed an isolated copy — never write back to host auth files from dev stacks).

```bash
make test-e2e
# Or: ./dev-env.sh start 1 && ./dev-env.sh test 1 -- -m "integration and smoke"
```

Gate C is opt-in in CI: add the `run-e2e` PR label or run `workflow_dispatch` on the CI workflow. Hotspot paths do **not** auto-require `real-provider-e2e`.

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
| Unit tests | `make test-unit` (`-n auto`) | `unit-tests` (builds gateway-engine image inline) |
| Mock integration | `make test-mock` | `mock-integration` (path-filtered; in-memory pytest) |
| Multi-repo isolation | `bash tests/test-multi-repo-isolation.sh` | `multi-repo-isolation` (path-filtered) |
| Credential prober | path-filtered | `credential-prober` when `services/credential-prober/**` changes |
| `make test-fast` | lint + unit + policy validation + mock | Does **not** run isolation — run isolation script when touching `dev-env.sh`, `cliproxy-setup.sh`, etc. |

There is **no** separate `build-gateway-engine` or `policy-engine-tests` CI job.
