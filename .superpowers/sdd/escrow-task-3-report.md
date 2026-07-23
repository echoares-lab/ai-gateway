# Escrow Task 3 Report

## Status

Implemented the protected stable-key admin contracts, endpoint tests, OpenAPI
schemas, typed statuses, and mixed-version API guidance.

## Delivered behavior

- `POST /admin/keys` authenticates before parsing the body and delegates stable
  creation to `LauncherKeyService.create_key` instead of proxying LiteLLM.
- `GET /admin/keys/{alias}/secret` recovers slash-delimited aliases after
  explicit path validation.
- `POST /admin/keys/{alias}/import` validates, verifies, and imports a supplied
  legacy token through the stable-key service.
- Successful secret bodies contain `key`; auth, validation, and service errors
  use fixed redacted bodies and never interpolate exception text.
- All stable-key endpoint responses include `Cache-Control: no-store`.
- Stable service codes map to typed HTTP statuses: 404 (missing), 409
  (not escrowed/identity mismatch), 503 (store unavailable), and 502
  (incomplete creation).
- The OpenAPI registry documents request/response schemas, status codes,
  security, and mixed-version behavior.

## TDD evidence

Initial RED:

```text
python3 -m pytest test_gateway_engine_admin_api.py -q
14 failed, 8 passed
```

Security validation RED:

```text
python3 -m pytest test_gateway_engine_admin_api.py -q \
  -k 'validation_is_no_store or auth_precedes_body_validation'
2 failed, 22 deselected
```

Focused GREEN:

```text
python3 -m pytest test_gateway_engine_admin_api.py -q
24 passed, 1 warning in 0.49s
```

Full gateway-engine suite:

```text
python3 -m pytest -q
336 passed, 1 warning in 1.59s
```

Modified-file lint and format:

```text
python3 -m ruff format --check services/gateway-engine/admin_api.py \
  services/gateway-engine/test_gateway_engine_admin_api.py
2 files already formatted

python3 -m ruff check services/gateway-engine/admin_api.py \
  services/gateway-engine/test_gateway_engine_admin_api.py
All checks passed!
```

Documentation validation:

```text
OpenAPI YAML parsed and stable-key paths/schemas registered
git diff --check
# exit 0
```

## Gate limitation

`make test-fast` stops in repository-wide `ruff format --check` because the
unchanged reviewed Task 1/2 files `core/launcher_key_escrow.py` and
`test_gateway_engine_launcher_key_escrow.py` are not formatted according to the
currently installed Ruff version. Ruff check passes repository-wide. This task
does not reformat those dependency-owned files.

The pre-existing Starlette `TestClient`/`httpx` deprecation warning remains.

## Review note

The required independent review agent could not be spawned because all four
collaboration slots were occupied. Coordinator review is still required before
integration.
