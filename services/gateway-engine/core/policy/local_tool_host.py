"""Isolated, bounded local MCP tool-host adapter (C-RT-4 #607).

The adapter is deliberately not wired into an HTTP route. Callers must opt in
with ``LOCAL_MCP_TOOL_HOST_ENABLED`` and provide an explicit alias registry and
visibility predicate. A deployment should run this component in a dedicated
non-root, read-only container with networking disabled.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

MAX_REQUEST_BYTES = 1 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_JSON_DEPTH = 32
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TRACE_ALIAS_BYTES = 128


class ToolHostError(Exception):
    """Stable, non-sensitive local host error."""

    code = "tool_host_error"


class ToolHostDisabled(ToolHostError):
    code = "tool_host_disabled"


class ToolAliasDenied(ToolHostError):
    code = "tool_alias_denied"


class ToolBoundsExceeded(ToolHostError):
    code = "tool_bounds_exceeded"


class ToolTimedOut(ToolHostError):
    code = "tool_timeout"


@dataclass(frozen=True)
class LocalToolHostConfig:
    enabled: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_request_bytes: int = MAX_REQUEST_BYTES
    max_response_bytes: int = MAX_RESPONSE_BYTES
    max_json_depth: int = MAX_JSON_DEPTH
    read_only: bool = True
    network_enabled: bool = False

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= DEFAULT_TIMEOUT_SECONDS:
            raise ValueError("timeout exceeds local tool-host contract")
        if not 0 < self.max_request_bytes <= MAX_REQUEST_BYTES:
            raise ValueError("request bound exceeds local tool-host contract")
        if not 0 < self.max_response_bytes <= MAX_RESPONSE_BYTES:
            raise ValueError("response bound exceeds local tool-host contract")
        if not 0 < self.max_json_depth <= MAX_JSON_DEPTH:
            raise ValueError("JSON depth exceeds local tool-host contract")

    @classmethod
    def from_env(cls) -> "LocalToolHostConfig":
        enabled = os.environ.get("LOCAL_MCP_TOOL_HOST_ENABLED", "").lower() in ("1", "true", "yes")
        return cls(enabled=enabled)


def _json_depth(value: Any, depth: int = 0) -> int:
    if depth > MAX_JSON_DEPTH:
        return depth
    if isinstance(value, dict):
        return max((_json_depth(item, depth + 1) for item in value.values()), default=depth)
    if isinstance(value, list):
        return max((_json_depth(item, depth + 1) for item in value), default=depth)
    return depth


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ToolBoundsExceeded from exc


def _safe_alias(alias: Any) -> str:
    if not isinstance(alias, str) or not alias.strip():
        raise ToolAliasDenied
    value = alias.strip()
    if (
        len(value.encode("utf-8")) > MAX_TRACE_ALIAS_BYTES
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value) is None
    ):
        raise ToolAliasDenied
    return value


@dataclass
class LocalToolHost:
    """Execute explicitly registered callables with bounded resources."""

    registry: Mapping[str, Callable[[dict[str, Any]], Any | Awaitable[Any]]]
    is_visible: Callable[[str], bool]
    config: LocalToolHostConfig = LocalToolHostConfig()
    trace: Callable[..., None] | None = None

    def _record(self, *, request_id: str | None, alias: str, duration_ms: float, outcome: str, size: int) -> None:
        if self.trace is None:
            return
        self.trace(
            request_id=request_id or "-",
            alias=alias[:MAX_TRACE_ALIAS_BYTES],
            duration_ms=round(max(0.0, duration_ms), 3),
            outcome=outcome[:32],
            size=max(0, size),
        )

    async def invoke(
        self, alias: str, arguments: dict[str, Any] | None = None, *, request_id: str | None = None
    ) -> Any:
        started = time.monotonic()
        safe_alias = _safe_alias(alias)
        if not self.config.enabled:
            raise ToolHostDisabled
        if not self.config.read_only or self.config.network_enabled or os.geteuid() == 0:
            raise ToolAliasDenied
        if safe_alias not in self.registry or not self.is_visible(safe_alias):
            raise ToolAliasDenied
        payload = arguments if arguments is not None else {}
        request_size = _json_size(payload)
        if request_size > self.config.max_request_bytes or _json_depth(payload) > self.config.max_json_depth:
            raise ToolBoundsExceeded

        try:
            handler = self.registry[safe_alias]
            if inspect.iscoroutinefunction(handler):
                result = await asyncio.wait_for(handler(payload), timeout=self.config.timeout_seconds)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(handler, payload), timeout=self.config.timeout_seconds
                )
                if inspect.isawaitable(result):
                    result = await asyncio.wait_for(result, timeout=self.config.timeout_seconds)
            response_size = _json_size(result)
            if response_size > self.config.max_response_bytes or _json_depth(result) > self.config.max_json_depth:
                raise ToolBoundsExceeded
            self._record(
                request_id=request_id,
                alias=safe_alias,
                duration_ms=(time.monotonic() - started) * 1000,
                outcome="ok",
                size=response_size,
            )
            return result
        except asyncio.TimeoutError as exc:
            self._record(
                request_id=request_id,
                alias=safe_alias,
                duration_ms=(time.monotonic() - started) * 1000,
                outcome="timeout",
                size=0,
            )
            raise ToolTimedOut from exc
        except asyncio.CancelledError:
            self._record(
                request_id=request_id,
                alias=safe_alias,
                duration_ms=(time.monotonic() - started) * 1000,
                outcome="cancelled",
                size=0,
            )
            raise
        except ToolHostError:
            self._record(
                request_id=request_id,
                alias=safe_alias,
                duration_ms=(time.monotonic() - started) * 1000,
                outcome="bounds",
                size=0,
            )
            raise
        except Exception as exc:
            self._record(
                request_id=request_id,
                alias=safe_alias,
                duration_ms=(time.monotonic() - started) * 1000,
                outcome="error",
                size=0,
            )
            raise ToolHostError from exc


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "LocalToolHost",
    "LocalToolHostConfig",
    "MAX_JSON_DEPTH",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "ToolAliasDenied",
    "ToolBoundsExceeded",
    "ToolHostDisabled",
    "ToolHostError",
    "ToolTimedOut",
]
