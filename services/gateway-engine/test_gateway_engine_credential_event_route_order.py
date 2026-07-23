"""Ensure POST /v1/events/credential is registered before the catch-all proxy."""

from __future__ import annotations

import os
import sys

from starlette.routing import Match

sys.path.insert(0, os.path.dirname(__file__))
import main as t


def test_credential_event_route_registered_before_catchall_proxy():
    credential_idx = None
    catchall_idx = None
    for i, route in enumerate(t.app.routes):
        subroutes = getattr(getattr(route, "original_router", None), "routes", [route])
        for sub in subroutes:
            path = getattr(sub, "path", None)
            name = getattr(sub, "name", None)
            if path == "/v1/events/credential" or name == "handle_policy_credential_event":
                if credential_idx is None:
                    credential_idx = i
            if path == "/{path:path}" or name == "proxy":
                if catchall_idx is None:
                    catchall_idx = i

    assert credential_idx is not None, "credential event route missing"
    assert catchall_idx is not None, "catch-all proxy route missing"
    assert credential_idx < catchall_idx, (
        f"credential events at index {credential_idx} must precede catch-all at {catchall_idx}"
    )


def test_credential_event_path_matches_dedicated_handler_not_proxy():
    scope = {
        "type": "http",
        "path": "/v1/events/credential",
        "method": "POST",
        "headers": [],
    }
    matched = None
    for route in t.app.routes:
        if not hasattr(route, "matches"):
            continue
        match, _ = route.matches(scope)
        if match == Match.FULL:
            matched = route
            break

    assert matched is not None
    assert getattr(matched, "path", None) == "/v1/events/credential"
    assert getattr(matched, "name", None) == "handle_policy_credential_event"
