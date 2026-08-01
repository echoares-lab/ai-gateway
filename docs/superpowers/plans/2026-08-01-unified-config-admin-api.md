# C-SVC-4 Unified Config Admin API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a disabled-by-default, read-only `GET /admin/config` API that emits a bounded `config-snapshot.v1` projection of configuration provenance, safe structural settings, environment-reference presence, and model drift.

**Architecture:** A pure `api/config_snapshot.py` module parses and projects injected source data into the only valid snapshot shape. A separate `api/unified_config_admin.py` adapter owns fixed-path and live-source reads, strict scoped authentication, orchestration, bounds, and HTTP errors. The route is serialized behind contract and builder children; it never mutates or proxies configuration.

**Tech Stack:** Python 3.12, FastAPI, Pydantic-compatible dictionaries, PyYAML, httpx, pytest/pytest-asyncio, in-memory ASGI integration tests, Docker dev slots, OpenAPI YAML.

## Global Constraints

- Route is exactly `GET /admin/config`; schema is exactly `config-snapshot.v1`.
- `UNIFIED_CONFIG_ADMIN_API_ENABLED=false` is the default and rollback state.
- Enabled requests require `x-admin-key` and exact `x-management-scope: config:read`.
- Missing server auth is `503`; wrong/missing key is `401`; wrong scope is `403`; disabled is `404`.
- Every response, including errors, uses `Cache-Control: no-store`.
- Partial source failures return `200` with `status: degraded` and safe typed errors.
- No request parameter may select a source, file path, host, URL, or command.
- No raw YAML, environment value, secret, credential, URL, filesystem path, command, raw exception, or arbitrary upstream field may be returned or logged.
- Collections are sorted and capped at 256 entries; strings at 512 characters; nesting at depth 8.
- Deployed configuration input is capped at 1 MiB; serialized response is capped at 64 KiB.
- Live-source total timeout is five seconds with a two-second connect budget.
- Only `routing_strategy`, `cooldown_time`, `allowed_fails`, and `num_retries` are exposed from router settings.
- MCP projection contains alias and transport kind only.
- Production enablement, writes, reloads, GitOps promotion, policy mutation, team/key lifecycle, and UI changes are out of scope.
- Any new endpoint must be documented in `docs/openapi/`, `docs/ADMIN_ENDPOINT_EXPOSURE.yaml`, and `docs/API_DOCUMENTATION.md`.

---

## Coordination Precondition: Promote C-SVC-4

Before implementation, create an approved C-SVC-4 epic and three serialized ready children:

1. contract and deterministic fixtures;
2. pure snapshot builder; and
3. guarded adapter and API documentation.

Update `docs/ROADMAP.md` under **Now** and move C-SVC-4 from the unapproved candidate table into the promoted table in `docs/FEATURE_CANDIDATES.md`. Merge this documentation through a PR and record Gate D before any child is claimed.

Each child uses one claim ID, one branch, one worktree under `/home/dev/worktrees`, and slot 1 only when Gate C is required. Dependencies must point to the preceding merged child and its Gate D run.

Use these exact isolated branches and worktrees:

- promotion: `docs/csvc4-roadmap` at `/home/dev/worktrees/ai-gateway-csvc4-roadmap`;
- contract: `feat/csvc4-contract` at `/home/dev/worktrees/ai-gateway-csvc4-contract`;
- builder: `feat/csvc4-builder` at `/home/dev/worktrees/ai-gateway-csvc4-builder`;
- adapter: `feat/csvc4-api` at `/home/dev/worktrees/ai-gateway-csvc4-api`; and
- closeout: `docs/csvc4-closeout` at `/home/dev/worktrees/ai-gateway-csvc4-closeout`.

---

### Task 1: Executable Contract and Fixtures

**Files:**
- Create: `docs/UNIFIED_CONFIG_ADMIN_API_CONTRACT.md`
- Create: `services/gateway-engine/test_gateway_engine_unified_config_contract.py`
- Modify: `docs/API_DOCUMENTATION.md`

**Interfaces:**
- Consumes: `docs/superpowers/specs/2026-08-01-unified-config-admin-api-design.md`.
- Produces: fixture constants named `HEALTHY_INPUT`, `DEGRADED_INPUT`, `INVALID_CONFIG_INPUT`, `MISSING_ENV_INPUT`, `MODEL_DRIFT_INPUT`, and `SECRET_LOOKING_INPUT`; exact route/schema/error matrix for Tasks 2–3.

- [ ] **Step 1: Write the contract fixture test**

Create a pure test module with the required fixture names and assertions. It must not import `main`, FastAPI, or runtime implementation modules.

```python
from pathlib import Path

CONTRACT = Path(__file__).parents[2] / "docs" / "UNIFIED_CONFIG_ADMIN_API_CONTRACT.md"

HEALTHY_INPUT = {
    "litellm_yaml": "model_list:\n  - model_name: gpt-safe\n    litellm_params:\n      model: openai/gpt-safe\nrouter_settings:\n  routing_strategy: simple-shuffle\n",
    "registry_model_ids": ["gpt-safe"],
    "runtime_model_ids": ["gpt-safe"],
    "environment": {"OPENAI_API_KEY": "present-secret"},
}

DEGRADED_INPUT = {**HEALTHY_INPUT, "runtime_model_ids": None, "runtime_error": "source_timeout"}
INVALID_CONFIG_INPUT = {**HEALTHY_INPUT, "litellm_yaml": "model_list: ["}
MISSING_ENV_INPUT = {
    **HEALTHY_INPUT,
    "litellm_yaml": "model_list:\n  - model_name: gpt-safe\n    litellm_params:\n      api_key: os.environ/OPENAI_API_KEY\n",
    "environment": {},
}
MODEL_DRIFT_INPUT = {**HEALTHY_INPUT, "registry_model_ids": ["gpt-safe", "claude-safe"]}
SECRET_LOOKING_INPUT = {
    **HEALTHY_INPUT,
    "litellm_yaml": "model_list:\n  - model_name: gpt-safe\n    litellm_params:\n      api_key: sk-do-not-return\n      api_base: https://secret.example/v1\n",
}

def test_contract_defines_exact_boundary():
    text = CONTRACT.read_text(encoding="utf-8")
    for required in (
        "GET /admin/config",
        "config-snapshot.v1",
        "UNIFIED_CONFIG_ADMIN_API_ENABLED=false",
        "x-management-scope: config:read",
        "64 KiB",
        "1 MiB",
        "Cache-Control: no-store",
    ):
        assert required in text

def test_contract_fixture_names_are_stable():
    assert HEALTHY_INPUT["runtime_model_ids"] == ["gpt-safe"]
    assert DEGRADED_INPUT["runtime_error"] == "source_timeout"
    assert INVALID_CONFIG_INPUT["litellm_yaml"].endswith("[")
    assert MISSING_ENV_INPUT["environment"] == {}
    assert MODEL_DRIFT_INPUT["registry_model_ids"][-1] == "claude-safe"
    assert "sk-do-not-return" in SECRET_LOOKING_INPUT["litellm_yaml"]
```

- [ ] **Step 2: Run the contract test and confirm RED**

Run:

```bash
docker run --rm -v "$PWD:/repo" -w /repo/services/gateway-engine \
  ai-gateway-engine-test:latest \
  pytest test_gateway_engine_unified_config_contract.py -v
```

Expected: FAIL because `docs/UNIFIED_CONFIG_ADMIN_API_CONTRACT.md` does not exist.

- [ ] **Step 3: Write the contract document**

Create the contract with exact sections: purpose/source-of-truth; route/auth/flag matrix; `config-snapshot.v1` field table; safe projection allowlists; source and drift semantics; error matrix; bounds/redaction; fixtures; non-goals; rollback; and serialized dependencies. Copy every value from **Global Constraints** verbatim.

Add a C-SVC-4 contract entry to `docs/API_DOCUMENTATION.md` that points to the contract and states that the future endpoint must be registered in `docs/openapi/gateway-engine.yaml` before runtime merge.

- [ ] **Step 4: Run focused contract verification**

Run:

```bash
docker run --rm -v "$PWD:/repo" -w /repo/services/gateway-engine \
  ai-gateway-engine-test:latest \
  pytest test_gateway_engine_unified_config_contract.py -v
```

Expected: all contract tests PASS without importing runtime code.

- [ ] **Step 5: Run Gate A/B and commit**

Run:

```bash
make lint
make test-unit
make test-mock
```

Expected: all commands PASS.

Commit:

```bash
git add docs/UNIFIED_CONFIG_ADMIN_API_CONTRACT.md docs/API_DOCUMENTATION.md \
  services/gateway-engine/test_gateway_engine_unified_config_contract.py
git commit -m "docs(config): define unified config admin contract"
```

Open a PR, wait for required CI, merge, record Gate D, close the contract child, and clean its worktree before Task 2.

---

### Task 2: Pure Snapshot Builder

**Files:**
- Create: `services/gateway-engine/api/config_snapshot.py`
- Create: `services/gateway-engine/test_gateway_engine_config_snapshot.py`
- Read: `services/gateway-engine/test_gateway_engine_unified_config_contract.py`

**Interfaces:**
- Consumes: the six Task 1 fixtures and the exact contract.
- Produces:

```python
@dataclass(frozen=True)
class SnapshotInputs:
    litellm_yaml: str | None
    litellm_status: str
    registry_model_ids: tuple[str, ...] | None
    registry_status: str
    runtime_model_ids: tuple[str, ...] | None
    runtime_status: str
    environment: Mapping[str, str]
    generated_at: datetime
    source_errors: tuple[tuple[str, str], ...] = ()

def build_config_snapshot(inputs: SnapshotInputs) -> dict[str, Any]: ...
```

- [ ] **Step 1: Write failing fixture-to-builder tests**

Import the Task 1 fixtures and assert exact behavior:

```python
def test_healthy_snapshot_is_deterministic():
    snapshot = build_config_snapshot(_inputs(HEALTHY_INPUT))
    assert snapshot["schema"] == "config-snapshot.v1"
    assert snapshot["status"] == "ok"
    assert snapshot["models"]["configured"] == ["gpt-safe"]
    assert snapshot["drift"]["status"] == "clean"
    assert snapshot["routing"] == {"routing_strategy": "simple-shuffle"}

def test_secret_input_never_leaks_values_urls_or_paths():
    serialized = json.dumps(build_config_snapshot(_inputs(SECRET_LOOKING_INPUT)))
    for forbidden in ("sk-do-not-return", "secret.example", "https://", "/home/", "/root/"):
        assert forbidden not in serialized

def test_missing_runtime_source_is_unknown_not_false_drift():
    snapshot = build_config_snapshot(_inputs(DEGRADED_INPUT))
    assert snapshot["status"] == "degraded"
    assert snapshot["drift"]["status"] == "unknown"
    assert {error["code"] for error in snapshot["errors"]} == {"source_timeout"}
```

Also add tests for invalid YAML, missing environment reference, stable ties/order, public-prefix removal, safe provider-family projection, router allowlisting, MCP alias/transport-only projection, sanitized digest determinism, 256-entry truncation, 512-character truncation, and depth-8 redaction.

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```bash
docker run --rm -v "$PWD:/repo" -w /repo/services/gateway-engine \
  ai-gateway-engine-test:latest \
  pytest test_gateway_engine_config_snapshot.py -v
```

Expected: collection fails because `api.config_snapshot` does not exist.

- [ ] **Step 3: Implement types, parsing, and normalization**

Create `api/config_snapshot.py` with the exact `SnapshotInputs` interface. Add these constants and helpers:

```python
SCHEMA = "config-snapshot.v1"
MAX_ENTRIES = 256
MAX_STRING = 512
MAX_DEPTH = 8
SAFE_ROUTER_SETTINGS = ("allowed_fails", "cooldown_time", "num_retries", "routing_strategy")
ENV_REFERENCE = re.compile(r"(?:os\.environ/|\$\{)([A-Z_][A-Z0-9_]*)\}?")

def _bounded_text(value: object) -> str: ...
def _safe_provider_family(model_name: str, params: Mapping[str, Any]) -> str: ...
def _extract_environment_references(document: Mapping[str, Any]) -> list[str]: ...
def _sanitized_projection_digest(projection: Mapping[str, Any]) -> str: ...
```

Use `yaml.safe_load` only on `inputs.litellm_yaml`. Reject non-mapping roots as `source_invalid`. Omit unknown fields instead of recursively forwarding them.

- [ ] **Step 4: Implement projections and drift**

Implement `build_config_snapshot` so:

- configured, registry, and runtime aliases are normalized, deduplicated, sorted, and capped;
- `AI-Gateway:` is removed only from runtime-visible aliases;
- drift becomes `unknown` if any required comparison source is not `ok`;
- environment output is `[{'name': name, 'present': name in inputs.environment}]` and never includes values;
- source digests hash canonical JSON of the sanitized structural projection with `sort_keys=True` and compact separators;
- `generated_at` is UTC ISO-8601 and excluded from digests;
- `status` is `degraded` whenever any source is not `ok`, validation fails, or drift is non-clean.

- [ ] **Step 5: Run focused and adjacent tests**

Run:

```bash
docker run --rm -v "$PWD:/repo" -w /repo/services/gateway-engine \
  ai-gateway-engine-test:latest \
  pytest test_gateway_engine_config_snapshot.py \
    test_gateway_engine_unified_config_contract.py \
    test_gateway_engine_model_registry.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Run Gate A/B and commit**

Run `make lint`, `make test-unit`, and `make test-mock`; all must PASS.

Commit:

```bash
git add services/gateway-engine/api/config_snapshot.py \
  services/gateway-engine/test_gateway_engine_config_snapshot.py
git commit -m "feat(config): build safe unified config snapshots"
```

Open a PR, wait for required CI, merge, record Gate D, close the builder child, and clean its worktree before Task 3.

---

### Task 3: Guarded Source Adapter and Endpoint

**Files:**
- Create: `services/gateway-engine/api/unified_config_admin.py`
- Create: `services/gateway-engine/test_gateway_engine_unified_config_admin.py`
- Create: `tests/integration/test_unified_config_admin.py`
- Modify: `services/gateway-engine/core/config.py`
- Modify: `services/gateway-engine/main.py`
- Modify: `.env.example`
- Modify: `docs/openapi/gateway-engine.yaml`
- Modify: `docs/ADMIN_ENDPOINT_EXPOSURE.yaml`
- Modify: `docs/API_DOCUMENTATION.md`
- Modify: `docs/ops/RUNBOOK.md`

**Interfaces:**
- Consumes: `SnapshotInputs` and `build_config_snapshot` from Task 2.
- Produces:

```python
@dataclass(frozen=True)
class UnifiedConfigAdminDeps:
    load_litellm_text: Callable[[], str]
    load_registry_model_ids: Callable[[], tuple[str, ...]]
    fetch_runtime_model_ids: Callable[[], Awaitable[tuple[str, ...]]]
    environment: Callable[[], Mapping[str, str]]
    now: Callable[[], datetime]

def configure_unified_config_admin(deps: UnifiedConfigAdminDeps) -> None: ...
router: APIRouter
```

- [ ] **Step 1: Write failing endpoint tests**

Create injected dependency tests with exact assertions:

```python
def _headers(scope="config:read"):
    return {"x-admin-key": "admin-secret", "x-management-scope": scope}

def test_disabled_by_default_does_not_read_sources(monkeypatch, configured_client, source_spies):
    monkeypatch.delenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", raising=False)
    response = configured_client.get("/admin/config", headers=_headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "config_snapshot_disabled"
    assert source_spies.calls == []
    assert response.headers["cache-control"] == "no-store"

def test_enabled_requires_exact_scope(monkeypatch, configured_client):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    response = configured_client.get("/admin/config", headers=_headers("config:generate"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "config_snapshot_scope_forbidden"

def test_source_timeout_returns_degraded_snapshot(monkeypatch, timeout_client):
    monkeypatch.setenv("UNIFIED_CONFIG_ADMIN_API_ENABLED", "true")
    response = timeout_client.get("/admin/config", headers=_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["drift"]["status"] == "unknown"
```

Add tests for missing server auth (`503`), wrong key (`401`), healthy success, fixed-path source too large, each source failing independently, five-second timeout, safe logging, 64-KiB response rejection, and `no-store` on every response.

- [ ] **Step 2: Run endpoint tests and confirm RED**

Run:

```bash
docker run --rm -v "$PWD:/repo" -w /repo/services/gateway-engine \
  ai-gateway-engine-test:latest \
  pytest test_gateway_engine_unified_config_admin.py -v
```

Expected: collection fails because `api.unified_config_admin` does not exist.

- [ ] **Step 3: Implement the adapter boundary**

Create `api/unified_config_admin.py` with:

```python
router = APIRouter()
_NO_STORE = {"Cache-Control": "no-store"}
_SCOPE = "config:read"
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024
_FLAG_NAMES = ("UNIFIED_CONFIG_ADMIN_API_ENABLED", "GATEWAY_ENGINE_UNIFIED_CONFIG_ADMIN_API_ENABLED")
_deps: UnifiedConfigAdminDeps | None = None
```

Implement dynamic feature-flag evaluation, strict auth using `resolve_gateway_admin_key`, exact scope validation, bounded fixed-path reads, safe source-error mapping, and response serialization with compact JSON. Do not accept query parameters. If the serialized snapshot exceeds `_MAX_RESPONSE_BYTES`, return `502 config_snapshot_too_large` without any snapshot content.

- [ ] **Step 4: Wire fixed dependencies and configuration**

Add to `core/config.py`:

```python
UNIFIED_CONFIG_ADMIN_API_ENABLED = _env_bool(
    ("UNIFIED_CONFIG_ADMIN_API_ENABLED", "GATEWAY_ENGINE_UNIFIED_CONFIG_ADMIN_API_ENABLED"),
    False,
)
```

In `main.py`, configure the adapter with:

- `LITELLM_CONFIG_PATH` as the only file source;
- `_model_registry_store().list_models()` projected to model IDs only when
  `registry_available` is true; do not treat LiteLLM config fallback rows as a
  live registry source;
- `_admin_fetch_visible_models()` projected to a tuple or mapped safe source error;
- `os.environ` through a copied mapping; and
- `datetime.now(timezone.utc)` through the injected clock.

Then call `app.include_router(unified_config_admin_router)` before the catch-all proxy.

Add `UNIFIED_CONFIG_ADMIN_API_ENABLED=false` to `.env.example` with an operator-only comment.

- [ ] **Step 5: Register and document the endpoint**

Add the complete OpenAPI operation for `GET /admin/config`, including required headers, `config-snapshot.v1` success schema, typed `401/403/404/502/503` responses, and `Cache-Control: no-store` description.

Add exactly this exposure entry:

```yaml
- {method: GET, path: /admin/config, source: services/gateway-engine/api/unified_config_admin.py, exposure: internal-ingress, auth: "UNIFIED_CONFIG_ADMIN_API_ENABLED=true; x-admin-key + x-management-scope=config:read", boundary: "Traefik internal ingress; disabled by default"}
```

Update `docs/API_DOCUMENTATION.md` and `docs/ops/RUNBOOK.md` with the route, disabled default, sample authenticated read, safe response contents, and rollback command. Do not document production enablement.

- [ ] **Step 6: Add mock integration coverage**

Create `tests/integration/test_unified_config_admin.py` with `@pytest.mark.mock` tests for disabled default, enabled authentication matrix, healthy fixed-source response, degraded runtime-source response, and rollback to disabled. Assert zero provider OAuth calls and absence of fixture secrets in serialized output.

- [ ] **Step 7: Run focused, Gate A, and Gate B verification**

Run:

```bash
docker run --rm -v "$PWD:/repo" -w /repo/services/gateway-engine \
  ai-gateway-engine-test:latest \
  pytest test_gateway_engine_unified_config_admin.py \
    test_gateway_engine_config_snapshot.py \
    test_gateway_engine_unified_config_contract.py -v
make lint
make test-unit
make test-mock
python3 scripts/ops/validate_admin_exposure.py
python3 -c "import yaml; yaml.safe_load(open('docs/openapi/gateway-engine.yaml'))"
```

Expected: every command PASS, mock integration reports zero skips for the new test module, and admin exposure validation reports clean.

- [ ] **Step 8: Commit and open the runtime PR**

```bash
git add .env.example docs services/gateway-engine tests/integration/test_unified_config_admin.py
git commit -m "feat(config): add guarded unified config snapshot API"
```

Open a PR with risk level high because auth/config boundaries changed. Wait for all required checks to pass before Gate C and merge.

---

### Task 4: Gate C, Merge, Gate D, and Closeout

**Files:**
- No source changes expected.
- Update PR and issue comments with evidence.

**Interfaces:**
- Consumes: merged-ready Task 3 branch and claimed slot 1.
- Produces: Gate C evidence, merged PR, successful Gate D run, closed child/epic, and clean repository state.

- [ ] **Step 1: Start isolated slot 1**

Run:

```bash
./dev-env.sh list
./dev-env.sh start 1
```

Expected: slot 1 is the only C-SVC-4 slot and all services become healthy.

- [ ] **Step 2: Verify disabled default and authentication matrix**

Use the dev gateway URL and assert:

- disabled default returns `404 config_snapshot_disabled`;
- enabled request without configured auth returns `503`;
- wrong key returns `401`;
- wrong scope returns `403`; and
- every response carries `Cache-Control: no-store`.

Enable the feature only in a temporary dev-slot override. Never edit production configuration.

- [ ] **Step 3: Verify healthy, degraded, and rollback behavior**

With injected or temporarily isolated source conditions, verify:

- healthy response is `config-snapshot.v1`, bounded, and contains only safe structural fields;
- unavailable runtime-visible models yield `200 status=degraded` and `drift.status=unknown`;
- no environment value, raw path, URL, command, key, or exception appears; and
- disabling the feature restores the `404` rollback state.

Run `./dev-env.sh test 1`; expected: Gate C suite PASS with no C-SVC-4 failures.

- [ ] **Step 4: Stop the slot and record evidence**

Run:

```bash
./dev-env.sh stop 1
./dev-env.sh list
```

Expected: no C-SVC-4 slot remains. Remove any temporary override file and verify `git status --short` is clean.

- [ ] **Step 5: Merge and verify production**

Merge only after required CI and Gate C evidence are posted. Watch the `production-health-heartbeat` run for the merge commit and require success before closing the runtime child and epic.

- [ ] **Step 6: Roadmap closeout and cleanup**

Open a docs-only closeout PR moving C-SVC-4 to **Completed** with contract, builder, adapter PRs and Gate D run links. After its Gate D succeeds:

```bash
git worktree remove /home/dev/worktrees/ai-gateway-csvc4-api
git branch -d feat/csvc4-api
git worktree prune
git worktree list
./dev-env.sh list
git status --short
```

Expected: only the stable checkout remains; no dev slots run; the stable checkout contains only the pre-existing user files `.cursorrules`, `uv.lock`, and `uv.toml` as untracked.
