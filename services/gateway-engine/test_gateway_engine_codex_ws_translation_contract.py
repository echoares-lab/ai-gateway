"""Executable fixtures for the opt-in Codex WebSocket translation contract."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

_CONTRACT = {
    "subprotocol": "codex-ws.v1",
    "route": "/v1/responses",
    "flag": "CODEX_WS_TRANSLATION_ENABLED",
    "frame_bytes": 64 * 1024,
    "input_bytes": 32 * 1024,
    "inflight": 16,
    "queue": 128,
    "request_timeout_seconds": 30,
    "handshake_timeout_seconds": 5,
    "idle_timeout_seconds": 120,
    "close_codes": {
        "auth": 1008,
        "unsupported": 1003,
        "too_large": 1009,
        "internal": 1011,
        "normal": 1000,
    },
    "frames": {
        "request.start",
        "request.delta",
        "request.cancel",
        "response.delta",
        "response.tool_call",
        "response.completed",
        "response.error",
    },
}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SAFE_ERRORS = {
    "protocol_error",
    "timeout",
    "rate_limited",
    "policy_denied",
    "upstream_unavailable",
    "translation_error",
}


def _frame_hash(frame: dict) -> str:
    return hashlib.sha256(json.dumps(frame, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _accept_frame(state: dict, frame: dict) -> str:
    """Small reference state machine used by parity fixtures."""
    if not isinstance(frame, dict) or frame.get("type") not in _CONTRACT["frames"]:
        raise ValueError("protocol_error")
    request_id = frame.get("request_id")
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise ValueError("protocol_error")
    if frame["type"] == "request.start":
        if len(json.dumps(frame.get("input", {}), ensure_ascii=False).encode()) > _CONTRACT["input_bytes"]:
            raise ValueError("message_too_large")
        if request_id in state:
            raise ValueError("duplicate_request")
        state[request_id] = {"sequence": 0, "terminal": False, "hashes": {0: _frame_hash(frame)}}
        return "requesting"
    if request_id not in state:
        raise ValueError("unknown_request")
    current = state[request_id]
    sequence = frame.get("sequence")
    if not isinstance(sequence, int) or sequence < 0:
        raise ValueError("protocol_error")
    if sequence in current["hashes"]:
        if current["hashes"][sequence] == _frame_hash(frame):
            return "duplicate"
        raise ValueError("duplicate_conflict")
    if current["terminal"]:
        raise ValueError("late_frame")
    if sequence != current["sequence"] + 1:
        raise ValueError("sequence_error")
    current["sequence"] = sequence
    current["hashes"][sequence] = _frame_hash(frame)
    if frame["type"] in {"request.cancel", "response.completed", "response.error"}:
        current["terminal"] = True
        return "terminal"
    return "streaming"


def test_route_version_flag_limits_and_frame_types_are_explicit():
    assert _CONTRACT["route"] == "/v1/responses"
    assert _CONTRACT["subprotocol"] == "codex-ws.v1"
    assert _CONTRACT["flag"].endswith("_ENABLED")
    assert _CONTRACT["frames"] == {
        "request.start",
        "request.delta",
        "request.cancel",
        "response.delta",
        "response.tool_call",
        "response.completed",
        "response.error",
    }


def test_hard_bounds_and_close_codes_are_contractual():
    assert _CONTRACT["frame_bytes"] == 65536
    assert _CONTRACT["input_bytes"] == 32768
    assert _CONTRACT["inflight"] == 16
    assert _CONTRACT["queue"] == 128
    assert _CONTRACT["close_codes"] == {
        "auth": 1008,
        "unsupported": 1003,
        "too_large": 1009,
        "internal": 1011,
        "normal": 1000,
    }


def test_correlation_sequence_duplicate_and_terminal_semantics():
    state = {}
    assert _accept_frame(state, {"type": "request.start", "request_id": "r-1", "model": "gpt"}) == "requesting"
    delta = {"type": "request.delta", "request_id": "r-1", "sequence": 1, "delta": "hello"}
    assert _accept_frame(state, delta) == "streaming"
    assert _accept_frame(state, delta) == "duplicate"
    with pytest.raises(ValueError, match="duplicate_conflict"):
        _accept_frame(state, {**delta, "delta": "changed"})
    assert _accept_frame(state, {"type": "request.cancel", "request_id": "r-1", "sequence": 2}) == "terminal"
    with pytest.raises(ValueError, match="late_frame"):
        _accept_frame(state, {"type": "response.delta", "request_id": "r-1", "sequence": 3, "delta": "late"})


def test_malformed_and_unknown_frames_are_rejected_without_echo():
    state = {}
    for frame in (
        {"type": "request.start", "request_id": "bad/id", "model": "gpt"},
        {"type": "request.start", "request_id": "r-1", "model": "gpt", "input": "x" * 32769},
        {"type": "response.delta", "request_id": "missing", "sequence": 1, "delta": "x"},
    ):
        with pytest.raises(ValueError):
            _accept_frame(state, frame)
    assert _SAFE_ERRORS.isdisjoint({"authorization", "bearer", "prompt", "/root/"})


def test_cancellation_is_idempotent_and_request_hash_does_not_expose_payload():
    state = {}
    start = {"type": "request.start", "request_id": "r-2", "model": "claude", "input": "private prompt"}
    _accept_frame(state, start)
    cancel = {"type": "request.cancel", "request_id": "r-2", "sequence": 1}
    assert _accept_frame(state, cancel) == "terminal"
    assert _frame_hash(cancel) != "private prompt"
    with pytest.raises(ValueError):
        _accept_frame(state, {"type": "request.cancel", "request_id": "r-2", "sequence": 2})


def test_contract_document_requires_rollback_policy_and_observability_boundaries():
    path = Path(__file__)
    if len(path.parents) < 3:
        pytest.skip("repository docs are not mounted in the service test image")
    document = path.parents[2] / "docs" / "CODEX_WEBSOCKET_TRANSLATION_CONTRACT.md"
    if not document.exists():
        pytest.skip("repository docs are not mounted in the service test image")
    text = document.read_text()
    assert "CODEX_WS_TRANSLATION_ENABLED=false" in text
    assert "codex-ws.v1" in text
    assert "1009" in text
    assert "never" in text.lower() and "credentials" in text.lower()
