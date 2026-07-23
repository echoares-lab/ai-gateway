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
