import subprocess
import json

def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()

epic_body = """## Summary
Refactor the mock integration test suite to use in-memory ASGI testing with `TestClient` and `respx`, drastically reducing CI execution time and enabling precise fault injection. This will replace the reliance on `docker-compose.mock.yml` and network-bound containers.

## Problem
The current integration test suite uses `docker-compose.mock.yml` and spins up the full stack including network-bound mock upstream containers. This makes the CI slow, flaky, and makes it hard to test edge cases like specific HTTP failures.

## Why now
We need faster feedback loops in CI and more deterministic testing for edge cases to improve our developer velocity and the reliability of testing.

## Scope
- Scaffold in-memory testing fixtures (`conftest.py`)
- Build mock configurations for LiteLLM routes.
- Port existing integration tests (`test_policy_failover.py`, `test_gateway.py`).
- Add edge-case fault tests.
- Decommission the external mock stack.

## Non-goals
- Changing the production architecture.
- Porting e2e tests that rely on real providers.

## Dependencies
- None

## Affected files / areas
- `tests/integration/`
- `tests/mock-upstream/`
- `docker-compose.mock.yml`
- `.github/workflows/ci.yml`
"""

epic_url = run(["gh", "issue", "create", "--title", "[Epic] Mock Integration In-Memory Refactor", "--body", epic_body, "--label", "type:code-health,area:tests,priority:medium,status:ready"])
epic_id = epic_url.split("/")[-1]
print(f"Created Epic: {epic_id}")

issues = [
    {
        "title": "Scaffold In-Memory Fixtures (conftest.py)",
        "body": """## Summary
Setup `respx` router, `httpx.AsyncClient` with the Gateway Engine ASGI app, and `fakeredis` backend in `tests/integration/conftest.py`.

## Problem
We need the foundational fixtures and mocking infrastructure to support in-memory ASGI testing.

## Why now
This is the prerequisite for porting existing tests and decommissioning the slow docker-compose mock stack.

## Scope
- Create `tests/integration/conftest.py` updates to provide an `asgi_client` fixture.
- Wire `fakeredis` into the gateway-engine's state initialization when running tests.
- Add `respx` to test dependencies if needed.

## Non-goals
- Porting the actual tests.

## Acceptance criteria
- `conftest.py` provides an `asgi_client` fixture.
- Tests can run using this fixture.

## Required tests
- N/A (this is test infra)

## Risks / rollback notes
- Low risk.

## Dependencies
- Bundle: #{epic_id}

## Affected files / areas
- `tests/integration/conftest.py`
- `tests/integration/requirements.txt` (or pyproject.toml / pip setup)
""",
        "labels": "type:test,area:tests,priority:medium,status:ready",
        "depends_on": []
    },
    {
        "title": "Build LiteLLM Route Mocks",
        "body": """## Summary
Create reusable `respx` mock configurations for common LiteLLM endpoints (`/v1/chat/completions`, `/v1/models`, health).

## Problem
In-memory tests need to simulate responses from the downstream LiteLLM service, previously handled by `mock-upstream`.

## Why now
Prerequisite for porting existing scenario tests to in-memory testing.

## Scope
- Mock `/v1/chat/completions`
- Mock `/v1/models`
- Mock health endpoints.
- Mocks should be easily overridable by individual tests.

## Non-goals
- Full feature parity with the actual LiteLLM API, only what's needed for the gateway proxy tests.

## Acceptance criteria
- Mock utilities are available and functional in tests.

## Required tests
- N/A (this is test infra)

## Risks / rollback notes
- Low risk.

## Dependencies
- Bundle: #{epic_id}
- Depends on: {{ISSUE_1}}

## Affected files / areas
- `tests/integration/conftest.py` or a new mock module.
""",
        "labels": "type:test,area:tests,priority:medium,status:ready",
        "depends_on": [0]
    },
    {
        "title": "Port `test_policy_failover.py` to In-Memory",
        "body": """## Summary
Rewrite failover scenarios to use the `asgi_client` and `respx` mocks instead of the external gateway.

## Problem
The test currently relies on `docker-compose.mock.yml` and is slow/flaky.

## Why now
Moving tests to in-memory speeds up CI.

## Scope
- Update `tests/integration/test_policy_failover.py`.
- Replace setup/teardown logic that relied on external service state.

## Non-goals
- Adding new failover scenarios.

## Acceptance criteria
- Failover tests pass using the `asgi_client`.

## Required tests
- N/A (this is a test migration)

## Risks / rollback notes
- Medium risk: ensure we aren't losing test coverage inadvertently.

## Dependencies
- Bundle: #{epic_id}
- Depends on: {{ISSUE_2}}

## Affected files / areas
- `tests/integration/test_policy_failover.py`
""",
        "labels": "type:test,area:tests,priority:medium,status:ready",
        "depends_on": [1]
    },
    {
        "title": "Port `test_gateway.py` to In-Memory",
        "body": """## Summary
Migrate general gateway proxying and auth tests to use in-memory fixtures.

## Problem
The test currently relies on `docker-compose.mock.yml`.

## Why now
Speeds up CI.

## Scope
- Update `tests/integration/test_gateway.py` ensuring all basic proxying assertions still pass against the ASGI client.

## Non-goals
- Adding new tests.

## Acceptance criteria
- Tests pass using the `asgi_client`.

## Required tests
- N/A (this is a test migration)

## Risks / rollback notes
- Medium risk.

## Dependencies
- Bundle: #{epic_id}
- Depends on: {{ISSUE_2}}

## Affected files / areas
- `tests/integration/test_gateway.py`
""",
        "labels": "type:test,area:tests,priority:medium,status:ready",
        "depends_on": [1]
    },
    {
        "title": "Implement Edge-Case Fault Tests",
        "body": """## Summary
Add tests simulating specific network and upstream failures using `respx.mock`.

## Problem
These tests were hard/impossible to implement cleanly with `docker-compose.mock.yml`.

## Why now
We need to ensure the system gracefully handles upstream failures (timeouts, 502s, malformed JSON).

## Scope
- Add a test for read timeouts (simulated via `respx` exceptions).
- Add a test for 502 Bad Gateway responses from the upstream provider.
- Add a test for malformed JSON responses from LiteLLM.

## Non-goals
- Handling every conceivable network error, just the most common ones.

## Acceptance criteria
- New tests are added and passing using in-memory architecture.

## Required tests
- N/A (these are the new tests)

## Risks / rollback notes
- Low risk.

## Dependencies
- Bundle: #{epic_id}
- Depends on: {{ISSUE_2}}

## Affected files / areas
- `tests/integration/`
""",
        "labels": "type:test,area:tests,priority:medium,status:ready",
        "depends_on": [1]
    },
    {
        "title": "Decommission External Mock Infrastructure",
        "body": """## Summary
Remove the old mock network stack once the in-memory suite is fully operational.

## Problem
We have dead code and infrastructure (`docker-compose.mock.yml`, `mock-upstream`) once the tests are migrated.

## Why now
Clean up the repository and speed up CI pipelines by removing the container spin-up steps.

## Scope
- Remove `docker-compose.mock.yml`.
- Delete `tests/mock-upstream` container code.
- Update `Makefile` and `.github/workflows/ci.yml` to remove container spin-up for the mock integration job.

## Non-goals
- Touching production deployment scripts.

## Acceptance criteria
- Dead code/files removed.
- CI pipeline passes without the `mock-upstream` step.

## Required tests
- Must pass `make test-fast`.

## Risks / rollback notes
- Medium risk. Revert PR if it breaks CI on other branches.

## Dependencies
- Bundle: #{epic_id}
- Depends on: {{ISSUE_3}}, {{ISSUE_4}}, {{ISSUE_5}}

## Affected files / areas
- `docker-compose.mock.yml`
- `tests/mock-upstream/`
- `Makefile`
- `.github/workflows/ci.yml`
""",
        "labels": "type:code-health,area:infra,priority:medium,status:ready",
        "depends_on": [2, 3, 4]
    }
]

created_ids = []
for i, issue in enumerate(issues):
    body = issue["body"].replace("{epic_id}", epic_id)
    for j, dep in enumerate(issue["depends_on"]):
        body = body.replace(f"{{{{ISSUE_{dep+1}}}}}", f"#{created_ids[dep]}")
    
    url = run(["gh", "issue", "create", "--title", issue["title"], "--body", body, "--label", issue["labels"]])
    issue_id = url.split("/")[-1]
    created_ids.append(issue_id)
    print(f"Created Issue: {issue_id}")
