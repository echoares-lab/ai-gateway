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

## Review expansion

Expanded the stateful HTTP failure ledger to every requested recoverable boundary.

- Create: initial escrow read, pending write, pending CAS conflict, LiteLLM generate
  response loss after remote creation, post-generate token verification, and escrow
  activation.
- Import: pending escrow write and activation.
- Recovery: escrow read, LiteLLM alias lookup, and LiteLLM token verification.

Every create case retries to `STABLE_TOKEN`, proves the remote key contains that exact
token, records exactly one successful LiteLLM generation, and records zero OpenBao
`DELETE` requests. Every import case retries to `LEGACY_TOKEN`, records zero generation
and zero delete requests. Recovery retries preserve the original token with one prior
generation and zero deletes. The response-loss case simulates the critical ambiguous
boundary by creating the remote key before returning HTTP 503; retry discovers it by
the pending token instead of issuing another generation.

Log assertions now lowercase captured output and reject both header names
`authorization` and `x-vault-token`, as well as the stable, workload, and master secret
values. Revalidation after review: focused suite 14 passed; mock suite 65 passed with
three deselected and one pre-existing warning; `make test-fast` passed with 324 gateway
unit tests and the same 65-test mock selection.

## Final boundary audit

Converted the create and import failure matrices to explicit phase/operation tables so
the service transaction can be audited row by row. Added the remaining boundaries:

- Create pre-write: transient LiteLLM alias lookup failure.
- Import lookup: transient LiteLLM alias lookup and escrow read failures.
- Import verification: transient supplied-token verification failure.

Together with the earlier rows, the tables now cover seven recoverable create
boundaries, five import boundaries, and three recovery boundaries. Every added case
retries to the exact stable or legacy token, asserts one successful generation for
create and zero for import, and proves the HTTP ledger contains no `DELETE` request.

Final verification: focused suite 18 passed; mock suite 69 passed with three deselected
and one pre-existing warning. The initial `make test-fast` invocation collided with a
concurrent process using the Makefile's fixed test-container name; rerunning through
the supported `CONTAINER_PREFIX=ESCROW5-` override passed with 324 gateway unit tests
and the 69-test mock selection.

## Pinned-contract integration correction

Updated the stateful LiteLLM mock to match v1.93.0: `/key/list` requires
`return_full_object=true` and returns a hash in `token`; `/key/info` returns only
alias/team identity in `info`. The mock stores the secret separately from the stable
hash, so the integration suite can no longer pass by accidentally treating a returned
secret or invented `key_id` as identity. Exact-token retry and zero-delete assertions
remain unchanged.

## Post-creation stable-identity lookup boundary

Added a distinct stateful failure injection for the second full-object `/key/list`
request, after LiteLLM generation and bearer-token authentication. Unlike the existing
pre-write list failure, this injection only fires after the remote alias exists. The
test proves the first attempt leaves the exact generated token in pending escrow, and
that retry returns that same token with exactly one generation call and no OpenBao
`DELETE`.

TDD evidence: before wiring the new injection into the stateful backend, the focused
case failed because creation completed instead of raising at the second list boundary.
After wiring it, the focused case passed and the integration file passed 19 tests.
Repository verification with `CONTAINER_PREFIX=ESCROW-POSTLIST- make test-fast`
passed, including 326 gateway unit tests and 70 mock integration tests with three
deselected and one pre-existing Starlette warning.
