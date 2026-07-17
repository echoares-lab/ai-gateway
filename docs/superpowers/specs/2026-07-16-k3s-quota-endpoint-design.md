# K3s Production Quota Endpoint Documentation Design

## Goal

Make the existing aggregate account-quota endpoint discoverable and usable against the k3s production Gateway Engine, and make the `quota-summary` helper display the same quota and reset-window data.

## Documentation

- Add `https://gateway.infra.plexplease.com` as the production server in `docs/openapi/gateway-engine.yaml`.
- Register `GET /admin/quota/status` in that OpenAPI document with optional `x-admin-key` authentication, response schemas, examples, and documented `502`, `503`, and authentication failures.
- Add production and authenticated curl examples to `docs/API_DOCUMENTATION.md`.
- Document that the endpoint aggregates CLIProxy passive quota state, live full-window state, and credential metadata, and may take up to 30 seconds.

## Helper Behavior

Change `./cliproxy-setup.sh quota-summary` to request `$GATEWAY_ENGINE_URL/admin/quota/status` instead of reading CLIProxy auth files directly. The existing default Gateway Engine URL remains local. Operators target production explicitly:

```bash
GATEWAY_ENGINE_URL=https://gateway.infra.plexplease.com ./cliproxy-setup.sh quota-summary
```

When `GATEWAY_ENGINE_ADMIN_KEY` is available from the environment or `.env`, the helper sends it as `x-admin-key`. The output groups accounts by provider and shows account state, plan, each available utilization window, reset timestamp, and relative reset timing where supplied.

## Failure Handling

The helper exits nonzero with a clear error when Gateway Engine is unreachable or returns a non-success response. It does not print the admin key. Empty account results are handled successfully with an explanatory message.

## Verification

- Add shell-level tests with a fake `curl` response for unauthenticated and authenticated calls, rendered quota windows, empty accounts, and HTTP failure.
- Run the helper tests and `bash -n cliproxy-setup.sh`.
- Validate the OpenAPI YAML and run the repository documentation validation available in the local environment.

## Related: staging deep-smoke (soft contract)

The staging deep-smoke promote gate
([spec](./2026-07-17-staging-deep-smoke-design.md), epic #396) calls
`GET /admin/quota/status` as a **soft** check (HTTP 2xx + parseable JSON object
only) until the OpenAPI response schema is frozen. Field-level asserts are
tracked in follow-up #403 — do not harden deep-smoke against a moving quota
shape while quota/alert work is in flight.
