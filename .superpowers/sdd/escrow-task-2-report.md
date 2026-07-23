# Escrow Task 2 Report

## Status

Implemented the stable launcher-key service transaction without adding or changing HTTP endpoints.

## Delivered behavior

- Generates LiteLLM-compatible `sk-` virtual keys with `secrets.token_urlsafe(32)`.
- Rejects a pre-existing remote alias without escrow and never rotates it.
- Writes a `pending` OpenBao record before calling LiteLLM `/key/generate`.
- Sends the exact escrowed token in LiteLLM's `key` creation field.
- Authenticates that exact token through `/key/info`, verifies alias/team identity, and activates the escrow record.
- Resumes a pending record with the same token, whether LiteLLM already created it or creation must be retried.
- Recovers only active records whose alias, team, and LiteLLM key ID match the remote identity.
- Imports a legacy token only after authenticating it, and refuses to overwrite a different active secret.
- Contains no delete, destroy, or rotation operation.

## TDD evidence

RED (before `core/launcher_key_service.py` existed):

```text
python3 -m pytest test_gateway_engine_launcher_key_escrow.py -q
10 failed, 17 passed
All 10 transaction tests failed with ModuleNotFoundError: core.launcher_key_service.
```

Focused GREEN and lint:

```text
python3 -m pytest test_gateway_engine_launcher_key_escrow.py -q
29 passed in 0.12s

python3 -m ruff check core/launcher_key_service.py test_gateway_engine_launcher_key_escrow.py
All checks passed!
```

Full gateway-engine suite:

```text
python3 -m pytest -q
319 passed, 1 warning in 1.20s
```

The warning is the pre-existing Starlette `TestClient`/`httpx` deprecation warning.

## Scope note

`admin_api.py` was intentionally not changed: Task 3 owns endpoint wiring and the brief explicitly prohibits adding endpoints in Task 2. The service is dependency-injected and ready for that wiring.

## Integrity follow-up (2026-07-23)

Two review findings were fixed without adding delete or rotation behavior:

- Recovery now authenticates the escrowed token through LiteLLM `/key/info` and requires its alias, team ID, and key ID to match both the active escrow record and the `/key/list` identity before returning the secret.
- Legacy import now requires an existing pending record's alias and team ID, plus its key ID when present, to match the authenticated remote identity before activation.
- Identity failures use the stable `key_identity_mismatch` code and never include the token in the error message.

TDD RED:

```text
python3 -m pytest test_gateway_engine_launcher_key_escrow.py -q -k 'recovery_checks_remote_and_escrow_identity or recovery_refuses_swapped_escrow_token or legacy_import_refuses_pending_record_identity_mismatch'
3 failed, 28 deselected in 0.14s
```

Focused GREEN and lint:

```text
python3 -m pytest test_gateway_engine_launcher_key_escrow.py -q
31 passed in 0.07s

python3 -m ruff check core/launcher_key_service.py test_gateway_engine_launcher_key_escrow.py
All checks passed!
```

Full gateway-engine suite:

```text
python3 -m pytest -q
321 passed, 1 warning in 1.34s
```

The warning remains the pre-existing Starlette `TestClient`/`httpx` deprecation warning.

## Pinned LiteLLM v1.93.0 contract correction

Whole-branch review found the original mocks invented `key_id` fields that the pinned
LiteLLM API does not return. Inspection of the pinned image source established the
real contract:

- `/key/list` returns stored token hashes only by default; with
  `return_full_object=true`, each object carries `token` (the stable hash),
  `key_alias`, and `team_id`.
- Bearer-authenticated `/key/info` removes the stored token from `info` and returns no
  key ID. Gateway-engine ignores its top-level key echo and uses only alias/team proof.

The service now requests full list objects, stores their token hash in the existing
`litellm_key_id` field as an opaque stable identity, and combines that identity with
bearer `/key/info` alias/team authentication. Tokens are never placed in query strings,
and creation, recovery, and import no longer rely on LiteLLM returning a secret or
invented key ID. Pinned-contract tests first failed on the absent
`return_full_object=true` request and then passed after the correction.
