# Escrow Task 5 — security and integration verification

## Scope completed

Added stateful mock-integration coverage that composes the real
`LauncherKeyService` with the real `OpenBaoEscrowClient` over an
`httpx.MockTransport` simulating both OpenBao KV-v2 and LiteLLM admin APIs.

- Create a launcher key, discard the returned value to simulate local cache loss, and
  recover the exact original token from escrow.
- Seed a pre-escrow LiteLLM key, import its token, and recover that exact legacy token.
- Inject recoverable failures at four transaction boundaries: OpenBao activation,
  OpenBao recovery read, LiteLLM alias lookup, and LiteLLM token verification.
- After every injected failure, retry successfully while asserting LiteLLM key
  generation remains exactly one call and the OpenBao request ledger contains no
  `DELETE` request.
- Capture DEBUG-level logs across create and recover and assert they contain none of
  the stable key, OpenBao workload token, LiteLLM master token, or `Authorization`
  header name.

This task adds verification only; the production transaction already satisfied these
integration contracts, so no runtime code changed.

## Verification evidence

- Focused integration:
  `python3 -m pytest tests/integration/test_launcher_key_escrow.py -q` — 7 passed.
- Ruff:
  `ruff check ... tests/integration/test_launcher_key_escrow.py` — passed;
  `ruff format --check ... tests/integration/test_launcher_key_escrow.py` — passed.
- Mock integration:
  `make test-mock` — 58 passed, 3 deselected, one pre-existing Starlette warning.
- OpenAPI offline validation: parsed `docs/openapi/gateway-engine.yaml`, verified an
  OpenAPI 3 document, required info/paths/components, and all three stable-key paths;
  24 paths validated.
- Repository secret scanner:
  `CHECK_ALL=1 bash .githooks/prevent-hardcoded-keys.sh` — no hardcoded keys found.
- Repository prescribed fast suite: `make test-fast` — passed, including 324 gateway
  unit tests, 24 probe-classifier tests, four shell probe cases, two compose-migration
  tests, and 58 mock integration tests; one pre-existing warning.
- `git diff --check` — passed.
