# Model reconciliation Task 6 report

Base: `78cd2a0`

## Delivered

- Added Gate B mock integration coverage for the complete trusted discovery
  lifecycle: CLIProxy advertises `gpt-5.6-sol`, reconciliation normalizes it to
  `gpt-5-6-sol`, probes it healthy, renders and atomically applies artifacts,
  reloads LiteLLM, verifies the reloaded catalog, persists the registry record,
  and exposes `AI-Gateway:gpt-5-6-sol` through the real gateway `/v1/models`
  route.
- Added the negative demand case where a client requests
  `gpt-9-9-client-invented` but CLIProxy advertises no such model. The run
  performs no reload, creates no registry record, and the gateway catalog never
  advertises the client-supplied name.
- Kept all external components in-memory while exercising production
  reconciliation, normalization, rendering, atomic artifact management, and
  gateway routing code.

## TDD evidence

- Initial RED exposed an invalid test boundary: using the ASGI client for
  absolute upstream URLs sent CLIProxy and LiteLLM requests back through the
  gateway. Both lifecycle cases failed.
- Separating the gateway-facing ASGI client from the mocked upstream HTTP
  client made the service boundaries accurate. Both focused cases then passed
  without production changes, confirming Task 6 was a verification gap.

## Verification

- Focused lifecycle file: `2 passed`.
- Gate B: `python3 -m pytest tests/integration/ -m mock -v` — `53 passed`,
  `3 deselected`, with one pre-existing Starlette/httpx warning.
- The plan's literal `.venv-ci/bin/python` was unavailable in this worktree, so
  Gate B used the repository's active `python3` environment with the identical
  test selection.
- Gateway unit suite: `373 passed`.
- Sync-model probe tests: `24 passed`; all four shell classification checks
  passed.
- `CONTAINER_PREFIX=MODEL-TASK6- make test-fast` — passed, including Ruff,
  format checking, units, policy/profile checks, drift, probe classification,
  compose validation, and Gate B.
