"""Account budget gates — soft quota headroom + hard team budget (issue 38-9).

Hard deny is gated on ``BUDGET_HARD_GATE_ENABLED`` (default false) until P0-4
LiteLLM team budget enforcement lands. When disabled, exhausted budgets tag
``budget:hard_deny_skipped_fail_open`` instead of denying.

Soft deprioritization always applies when quota headroom is below the configured
threshold (``policy_json.budget.soft_gate_threshold_pct``, default 15%).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.policy.schemas import (
    BudgetSnapshot,
    GateAction,
    PolicyProfile,
    QuotaHeadroom,
    RoutingContext,
)

DEFAULT_SOFT_GATE_THRESHOLD_PCT = float(os.environ.get("BUDGET_SOFT_GATE_THRESHOLD_PCT", "15"))
DEFAULT_COST_TIER_THRESHOLD_PCT = float(os.environ.get("BUDGET_COST_TIER_THRESHOLD_PCT", "80"))
DEFAULT_HARD_GATE_RETRY_AFTER = int(os.environ.get("BUDGET_HARD_GATE_RETRY_AFTER", "60"))
HARD_GATE_ENABLED = os.environ.get("BUDGET_HARD_GATE_ENABLED", "false").lower() in (
    "1",
    "true",
    "yes",
)


@dataclass(frozen=True)
class BudgetConfig:
    soft_gate_threshold_pct: float = DEFAULT_SOFT_GATE_THRESHOLD_PCT
    cost_tier_threshold_pct: float = DEFAULT_COST_TIER_THRESHOLD_PCT
    cost_tier_preference: str | None = None
    hard_gate_enabled: bool = HARD_GATE_ENABLED


@dataclass
class BudgetGateResult:
    gate: GateAction = GateAction.ALLOW
    deny_reason: str | None = None
    retry_after_seconds: int | None = None
    deprioritized_credentials: list[str] | None = None
    credential_tier_preference: str | None = None
    rules_applied: list[str] | None = None

    def __post_init__(self) -> None:
        if self.deprioritized_credentials is None:
            self.deprioritized_credentials = []
        if self.rules_applied is None:
            self.rules_applied = []


def _budget_section(policy_json: dict) -> dict:
    section = policy_json.get("budget")
    return section if isinstance(section, dict) else {}


def extract_budget_config(profiles: list[PolicyProfile]) -> BudgetConfig:
    """Merge budget settings from layered profiles (least → most specific)."""
    config = BudgetConfig()
    soft_threshold = config.soft_gate_threshold_pct
    cost_threshold = config.cost_tier_threshold_pct
    cost_tier: str | None = None
    hard_enabled = config.hard_gate_enabled

    for profile in profiles:
        section = _budget_section(profile.policy_json)
        if "soft_gate_threshold_pct" in section:
            soft_threshold = float(section["soft_gate_threshold_pct"])
        if "cost_tier_threshold_pct" in section:
            cost_threshold = float(section["cost_tier_threshold_pct"])
        if section.get("cost_tier_preference"):
            cost_tier = str(section["cost_tier_preference"])
        if "hard_gate_enabled" in section:
            hard_enabled = bool(section["hard_gate_enabled"])

    return BudgetConfig(
        soft_gate_threshold_pct=soft_threshold,
        cost_tier_threshold_pct=cost_threshold,
        cost_tier_preference=cost_tier,
        hard_gate_enabled=hard_enabled,
    )


def _headroom_below_threshold(
    headroom: QuotaHeadroom,
    threshold_pct: float,
) -> bool:
    if headroom.below_soft_threshold:
        return True
    if headroom.headroom_pct is not None:
        return headroom.headroom_pct < threshold_pct
    return False


def _budget_exhausted(budget: BudgetSnapshot) -> tuple[bool, str | None]:
    if budget.team_budget_pct_used is not None and budget.team_budget_pct_used >= 100:
        return True, "team budget exhausted (100% used)"

    if (
        budget.team_budget_usd is not None
        and budget.team_spend_usd is not None
        and budget.team_spend_usd >= budget.team_budget_usd
    ):
        return True, "team dollar budget exhausted"

    if budget.rpm_remaining is not None and budget.rpm_remaining <= 0:
        return True, "team RPM budget exhausted"

    if budget.tpm_remaining is not None and budget.tpm_remaining <= 0:
        return True, "team TPM budget exhausted"

    return False, None


def apply_soft_headroom_gates(
    quota_headroom: list[QuotaHeadroom],
    *,
    threshold_pct: float,
) -> tuple[list[str], list[str]]:
    """Deprioritize credentials below quota headroom threshold."""
    deprioritized: list[str] = []
    rules: list[str] = []

    for headroom in quota_headroom:
        if not _headroom_below_threshold(headroom, threshold_pct):
            continue
        if headroom.credential_id not in deprioritized:
            deprioritized.append(headroom.credential_id)
        if "budget:soft_deprioritize" not in rules:
            rules.append("budget:soft_deprioritize")

    return deprioritized, rules


def apply_budget_gates(
    context: RoutingContext,
    profiles: list[PolicyProfile],
    *,
    hard_gate_enabled: bool | None = None,
) -> BudgetGateResult:
    """Evaluate soft headroom deprioritization and optional hard team budget deny."""
    config = extract_budget_config(profiles)
    hard_enabled = config.hard_gate_enabled if hard_gate_enabled is None else hard_gate_enabled

    deprioritized, rules = apply_soft_headroom_gates(
        context.quota_headroom,
        threshold_pct=config.soft_gate_threshold_pct,
    )

    tier_preference: str | None = None
    budget = context.budget
    if budget and budget.team_budget_pct_used is not None:
        if budget.team_budget_pct_used >= config.cost_tier_threshold_pct:
            tier_preference = config.cost_tier_preference
            if tier_preference:
                rules.append("budget:cost_tier_preference")

    if budget is None:
        return BudgetGateResult(
            deprioritized_credentials=deprioritized,
            credential_tier_preference=tier_preference,
            rules_applied=rules,
        )

    exhausted, reason = _budget_exhausted(budget)
    if not exhausted:
        return BudgetGateResult(
            deprioritized_credentials=deprioritized,
            credential_tier_preference=tier_preference,
            rules_applied=rules,
        )

    if not hard_enabled:
        rules.append("budget:hard_deny_skipped_fail_open")
        return BudgetGateResult(
            deprioritized_credentials=deprioritized,
            credential_tier_preference=tier_preference,
            rules_applied=rules,
        )

    rules.append("budget:hard_deny")
    return BudgetGateResult(
        gate=GateAction.DENY,
        deny_reason=reason,
        retry_after_seconds=DEFAULT_HARD_GATE_RETRY_AFTER,
        deprioritized_credentials=deprioritized,
        credential_tier_preference=tier_preference,
        rules_applied=rules,
    )
