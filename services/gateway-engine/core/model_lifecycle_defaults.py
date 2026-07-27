"""Default lifecycle-derived policy values until curated metadata exists."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.model_registry import ModelRegistryRecord

_FAMILY_DEFAULT_ORDER = {
    "openai": ["gemini", "anthropic"],
    "anthropic": ["gemini", "openai"],
    "gemini": ["anthropic", "openai"],
}


def default_fallbacks_for(
    model: ModelRegistryRecord,
    advertised_models: list[ModelRegistryRecord],
) -> list[str]:
    by_family: dict[str, list[str]] = {}
    for peer in advertised_models:
        if peer.model_id == model.model_id or peer.retired or not peer.advertised:
            continue
        by_family.setdefault(peer.family, []).append(peer.model_id)
    ordered: list[str] = []
    for family in _FAMILY_DEFAULT_ORDER.get(model.family, []):
        ordered.extend(sorted(by_family.get(family, [])))
    return ordered
