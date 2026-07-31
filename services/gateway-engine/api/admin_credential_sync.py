"""Credential inventory sync scheduler."""

from __future__ import annotations

import asyncio

from api.admin_panels import (
    GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN,
    GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC,
    GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC,
    _admin_error,
    _admin_redact,
    _credential_inventory_store,
    _fetch_cliproxy_auth_files,
    _main_attr,
    _redact_credential_records,
    log,
)
from core.credential_inventory import (
    CredentialInventorySyncRequest,
    CredentialInventorySyncResponse,
    CredentialTransition,
    reconcile_credentials,
    record_from_auth_file,
)
from core.policy.schemas import CredentialEvent

_credential_sync_lock = asyncio.Lock()


def _deps():
    from api.admin_routes import _deps as _route_deps

    return _route_deps()


async def _emit_credential_transition_to_policy(transition: CredentialTransition) -> bool:
    event = CredentialEvent(
        credential_id=transition.credential_id,
        provider=transition.provider,
        previous_status=transition.previous_status,
        new_status=transition.new_status,
        cool_down_until=transition.cool_down_until,
        reason=transition.reason,
    )
    return await _deps().process_credential_event(event)


async def _sync_credentials_from_cliproxy(
    body: CredentialInventorySyncRequest,
) -> CredentialInventorySyncResponse:
    """Sync CLIProxy auth-file state into credential_inventory."""
    async with _credential_sync_lock:
        store = _credential_inventory_store()
        files, errors = await _fetch_cliproxy_auth_files()
        credentials = [record_from_auth_file(item) for item in files]
        transitions: list[CredentialTransition] = []
        imported = 0

        if errors:
            return CredentialInventorySyncResponse(
                accepted=False,
                dry_run=body.dry_run,
                registry_available=store.enabled,
                discovered_count=len(credentials),
                imported_count=0,
                credentials=_redact_credential_records(credentials),
                errors=errors,
            )

        old_statuses: dict[str, str] = {}
        if store.enabled:
            try:
                old_statuses = store.existing_statuses()
            except Exception as exc:
                errors.append(
                    _admin_error(
                        "registry_read_error",
                        f"{type(exc).__name__}: {exc}",
                        "postgres:credential_inventory",
                    )
                )
        else:
            errors.append(
                _admin_error(
                    "registry_unavailable",
                    "DATABASE_URL or psycopg2 unavailable",
                    "postgres:credential_inventory",
                )
            )

        credentials, transitions = reconcile_credentials(credentials, old_statuses)

        if not body.dry_run and store.enabled and not errors:
            try:
                imported = store.upsert_credentials(credentials)
            except Exception as exc:
                errors.append(
                    _admin_error(
                        "registry_write_error",
                        f"{type(exc).__name__}: {exc}",
                        "postgres:credential_inventory",
                    )
                )
            else:
                for transition in transitions:
                    try:
                        emit_transition = _main_attr(
                            "_emit_credential_transition_to_policy",
                            _emit_credential_transition_to_policy,
                        )
                        await emit_transition(transition)
                    except Exception as exc:
                        errors.append(
                            _admin_error(
                                "policy_event_error",
                                f"{type(exc).__name__}: {exc}",
                                "gateway-engine:policy-event",
                            )
                        )
        elif body.dry_run:
            imported = len(credentials)

        return CredentialInventorySyncResponse(
            accepted=not errors,
            dry_run=body.dry_run,
            registry_available=store.enabled,
            discovered_count=len(credentials),
            imported_count=imported,
            credentials=_redact_credential_records(credentials),
            transitions=transitions,
            errors=errors,
        )


async def _run_scheduled_credential_sync() -> CredentialInventorySyncResponse:
    response = await _sync_credentials_from_cliproxy(
        CredentialInventorySyncRequest(
            dry_run=_main_attr("GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN", GATEWAY_ENGINE_CREDENTIAL_SYNC_DRY_RUN)
        )
    )
    log.info(
        "credential sync scheduler completed accepted=%s dry_run=%s discovered=%d imported=%d transitions=%d errors=%d",
        response.accepted,
        response.dry_run,
        response.discovered_count,
        response.imported_count,
        len(response.transitions),
        len(response.errors),
    )
    return response


async def _credential_sync_scheduler_loop() -> None:
    initial_delay = _main_attr(
        "GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC",
        GATEWAY_ENGINE_CREDENTIAL_SYNC_INITIAL_DELAY_SEC,
    )
    interval = _main_attr(
        "GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC",
        GATEWAY_ENGINE_CREDENTIAL_SYNC_INTERVAL_SEC,
    )
    if initial_delay:
        await asyncio.sleep(initial_delay)
    while True:
        try:
            run_sync = _main_attr("_run_scheduled_credential_sync", _run_scheduled_credential_sync)
            await run_sync()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("credential sync scheduler failed: %s: %s", type(exc).__name__, _admin_redact(str(exc))[0])
        await asyncio.sleep(interval)
