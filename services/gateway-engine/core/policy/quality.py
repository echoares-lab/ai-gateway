"""Evaluation-driven quality reorder (Epic #38, issue 38-19 Phase 5b).

Optional layer 5b after health-weighted order: reads ``policy_json.eval``
weights populated by an offline job. Fail-open when disabled or scores absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.policy.schemas import PolicyProfile

DEFAULT_TASK_CATEGORY = "chat"
RULE_TAG = "eval:quality_reorder"


@dataclass(frozen=True)
class EvalConfig:
    enabled: bool = False
    min_samples: int = 50
    window_days: int = 7
    task_category: str = "auto"
    weight_blend: float = 0.3
    model_scores: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class QualityReorderResult:
    candidates: list[str]
    applied: bool = False
    rules_applied: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)


def _eval_section(policy_json: dict[str, Any]) -> dict[str, Any]:
    section = policy_json.get("eval")
    return section if isinstance(section, dict) else {}


def _parse_model_scores(raw: Any) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict):
        return {}
    scores: dict[str, dict[str, float]] = {}
    for category, models in raw.items():
        if not isinstance(models, dict):
            continue
        parsed: dict[str, float] = {}
        for model, value in models.items():
            try:
                parsed[str(model)] = float(value)
            except (TypeError, ValueError):
                continue
        if parsed:
            scores[str(category)] = parsed
    return scores


def extract_eval_config(profiles: list[PolicyProfile]) -> EvalConfig:
    """Merge eval settings from layered profiles (least → most specific)."""
    enabled = False
    min_samples = 50
    window_days = 7
    task_category = "auto"
    weight_blend = 0.3
    model_scores: dict[str, dict[str, float]] = {}

    for profile in profiles:
        section = _eval_section(profile.policy_json)
        if "enabled" in section:
            enabled = bool(section["enabled"])
        if "min_samples" in section:
            try:
                min_samples = max(int(section["min_samples"]), 0)
            except (TypeError, ValueError):
                pass
        if "window_days" in section:
            try:
                window_days = max(int(section["window_days"]), 1)
            except (TypeError, ValueError):
                pass
        if section.get("task_category"):
            task_category = str(section["task_category"])
        if "weight_blend" in section:
            try:
                weight_blend = min(max(float(section["weight_blend"]), 0.0), 1.0)
            except (TypeError, ValueError):
                pass
        parsed = _parse_model_scores(section.get("model_scores"))
        if parsed:
            model_scores = parsed

    return EvalConfig(
        enabled=enabled,
        min_samples=min_samples,
        window_days=window_days,
        task_category=task_category,
        weight_blend=weight_blend,
        model_scores=model_scores,
    )


def resolve_task_category(
    config: EvalConfig,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Derive task category from request metadata or profile config."""
    metadata = metadata or {}
    raw = metadata.get("task_category")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if config.task_category != "auto":
        return config.task_category
    return DEFAULT_TASK_CATEGORY


def _combined_score(
    model: str,
    *,
    quality_scores: dict[str, float],
    health_scores: dict[str, float],
    weight_blend: float,
) -> float:
    quality = quality_scores.get(model, 0.0)
    health = health_scores.get(model, 0.0)
    if not health_scores:
        return quality
    return (1.0 - weight_blend) * health + weight_blend * quality


def apply_quality_reorder(
    candidates: list[str],
    *,
    requested_model: str,
    eval_config: EvalConfig,
    task_category: str,
    health_scores: dict[str, float] | None = None,
) -> QualityReorderResult:
    """Reorder eligible tail by blended health + quality scores (layer 5b)."""
    health_scores = health_scores or {}
    if not eval_config.enabled:
        return QualityReorderResult(candidates=list(candidates))

    category_scores = eval_config.model_scores.get(task_category)
    if not category_scores:
        return QualityReorderResult(candidates=list(candidates))

    if len(candidates) <= 1:
        return QualityReorderResult(candidates=list(candidates))

    head = candidates[:1] if candidates[0] == requested_model else []
    tail = candidates[len(head) :]
    if not tail:
        return QualityReorderResult(candidates=list(candidates))

    scored_tail = [m for m in tail if m in category_scores]
    if not scored_tail:
        return QualityReorderResult(candidates=list(candidates))

    tail.sort(
        key=lambda m: (
            -_combined_score(
                m,
                quality_scores=category_scores,
                health_scores=health_scores,
                weight_blend=eval_config.weight_blend,
            ),
            m,
        )
    )
    reordered = head + tail
    return QualityReorderResult(
        candidates=reordered,
        applied=True,
        rules_applied=[RULE_TAG],
        debug={
            "eval_task_category": task_category,
            "eval_weight_blend": eval_config.weight_blend,
            "eval_scores_used": {m: category_scores[m] for m in tail if m in category_scores},
        },
    )
