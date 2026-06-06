"""In-process policy evaluation (Epic 2, issue #181)."""

from __future__ import annotations

import asyncio
import logging
import os

from core.policy.evaluate import (
    POLICY_VERSION,
    evaluate,
    evaluate_async,
    get_inventory_store,
    get_profile_store,
    get_redis_store,
)
from core.policy.mock_scenarios import evaluate_mock_scenario
from core.policy.schemas import (
    CredentialEvent,
    EvaluateRequest,
    EvaluateResponse,
    GateAction,
    PolicyProfile,
    PolicyScope,
    RoutingContext,
    RoutingDecision,
    TenancyContext,
)

_MOCK_SCENARIOS = os.environ.get("POLICY_MOCK_SCENARIOS", "").lower() in ("1", "true", "yes")

log = logging.getLogger(__name__)


def policy_version() -> str:
    return POLICY_VERSION


class PolicyEvaluator:
    """Async facade over the in-process policy evaluator."""

    def __init__(
        self,
        *,
        store=None,
        profile_store=None,
        inventory_store=None,
    ) -> None:
        self._store = store
        self._profile_store = profile_store
        self._inventory_store = inventory_store

    @classmethod
    def from_env(cls) -> PolicyEvaluator:
        return cls(
            store=get_redis_store(),
            profile_store=get_profile_store(),
            inventory_store=get_inventory_store(),
        )

    async def evaluate(self, context: dict) -> dict | None:
        """Evaluate routing context; returns metadata-ready decision dict."""
        try:
            if _MOCK_SCENARIOS:
                return evaluate_mock_scenario(context)
            decision = await asyncio.to_thread(self._evaluate_sync, context)
            return decision.model_dump(mode="json")
        except Exception as exc:
            log.warning("in-process policy evaluate failed (%s)", exc)
            return None

    def _evaluate_sync(self, context: dict) -> RoutingDecision:
        req = EvaluateRequest(context=RoutingContext.model_validate(context))
        return evaluate(
            req,
            store=self._store,
            profile_store=self._profile_store,
            inventory_store=self._inventory_store,
        )


__all__ = [
    "CredentialEvent",
    "EvaluateRequest",
    "EvaluateResponse",
    "GateAction",
    "PolicyEvaluator",
    "PolicyProfile",
    "PolicyScope",
    "RoutingContext",
    "RoutingDecision",
    "TenancyContext",
    "evaluate",
    "evaluate_async",
    "policy_version",
]
