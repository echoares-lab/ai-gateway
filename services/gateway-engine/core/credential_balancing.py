"""Pure, deterministic multi-account credential selection."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

ELIGIBLE_STATUSES = frozenset({"HEALTHY", "DEGRADED"})


@dataclass(frozen=True)
class CredentialPoolMember:
    credential_id: str
    status: str = "HEALTHY"
    weight: int = 1


def select_credential(
    members: list[CredentialPoolMember],
    *,
    request_key: str,
    deprioritized: set[str] | frozenset[str] | None = None,
) -> str | None:
    """Select a weighted member with stable tie-breaking and no secret inputs."""
    deprioritized_ids = deprioritized or set()
    eligible = [
        member
        for member in members
        if member.status in ELIGIBLE_STATUSES and member.credential_id not in deprioritized_ids and member.weight > 0
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda member: member.credential_id)
    total_weight = sum(member.weight for member in eligible)
    bucket = int.from_bytes(hashlib.sha256(request_key.encode("utf-8")).digest()[:8], "big") % total_weight
    for member in eligible:
        if bucket < member.weight:
            return member.credential_id
        bucket -= member.weight
    return eligible[-1].credential_id
