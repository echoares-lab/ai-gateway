"""Shared proxy router deps and helpers."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx
from fastapi import APIRouter

log = logging.getLogger("gateway-engine.proxy_router")

router = APIRouter()


@dataclass(frozen=True)
class ProxyRouterDeps:
    get_http_client: Callable[[], httpx.AsyncClient]
    get_policy_evaluator: Callable[[], Any | None]
    cache_key: Callable[..., str | None]
    cache_get: Callable[[str], Awaitable[list[str] | None]]
    cache_set: Callable[[str, list[str]], Awaitable[None]]
    record_policy_trace: Callable[..., None]
    load_model_registry: Callable[[], Any]
    litellm_url: str
    model_prefix: str
    upstream_timeout: float
    enable_virtual_providers: Callable[[], bool]
    policy_engine_enabled: Callable[[], bool]
    team_budget_snapshot_enabled: Callable[[], bool]
    team_budget_cache_ttl_sec: int


_default_deps: ProxyRouterDeps | None = None


def configure_proxy_routes(deps: ProxyRouterDeps) -> None:
    global _default_deps
    _default_deps = deps


def _deps() -> ProxyRouterDeps:
    if _default_deps is None:
        raise RuntimeError("proxy router dependencies not configured")
    return _default_deps


def _http_client() -> httpx.AsyncClient:
    client = _deps().get_http_client()
    if client is None:
        raise RuntimeError("http client not initialized")
    return client


def _main_override(name: str, current: Any) -> Any | None:
    main_module = sys.modules.get("main")
    if main_module is None:
        return None
    candidate = getattr(main_module, name, None)
    if candidate is None or candidate is current:
        return None
    return candidate


def _enable_virtual_providers() -> bool:
    return bool(_deps().enable_virtual_providers())


async def _aiter_list(lst: list[str]):
    for item in lst:
        yield item


async def _tee_lines(aiter, buf: list[str]):
    async for line in aiter:
        buf.append(line)
        yield line
