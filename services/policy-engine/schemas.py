"""Routing policy request/response schemas (Epic #38, issue 38-1)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class PolicyScope(str, Enum):
    ORG = "org"
    WORKSPACE = "workspace"
    TEAM = "team"
    REPO = "repo"


class RequestCapabilities(BaseModel):
    """Shape-derived constraints used for capability-fit filtering."""

    has_tools: bool = False
    has_vision: bool = False
    estimated_tokens: int | None = Field(default=None, ge=0)
    active_tool_chain: bool = False
    model_family: str | None = None


class TenancyContext(BaseModel):
    tenant_id: str | None = None
    workspace_id: str | None = None
    team_id: str | None = None
    repo_name: str | None = None
    environment: str | None = None
    api_key_label: str | None = Field(
        default=None,
        description="Decoded ak-{org}-{workspace}-{team}-{repo}-{env} label when present.",
    )


class BudgetSnapshot(BaseModel):
    """Optional spend/rate snapshot for soft gates (Phase 2+)."""

    team_budget_usd: float | None = Field(default=None, ge=0)
    team_spend_usd: float | None = Field(default=None, ge=0)
    team_budget_pct_used: float | None = Field(default=None, ge=0, le=100)
    rpm_remaining: int | None = Field(default=None, ge=0)
    tpm_remaining: int | None = Field(default=None, ge=0)


class RateLimitSnapshot(BaseModel):
    """Per-request rate-limit hints from hot state (Redis / inventory)."""

    provider: str | None = None
    credential_id: str | None = None
    in_cooldown: bool = False
    cooldown_until: datetime | None = None
    rolling_429_count_5m: int = Field(default=0, ge=0)
    pre_emptive_degraded: bool = Field(
        default=False,
        description="True when rolling 429 rate exceeds threshold — deprioritize before hard 429.",
    )


class QuotaHeadroom(BaseModel):
    """Per-credential quota headroom for soft gates and quota-aware pool routing."""

    credential_id: str
    provider: str | None = None
    headroom_pct: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Remaining quota as % of limit (from inventory metadata or quota-summary).",
    )
    rpm_remaining: int | None = Field(default=None, ge=0)
    requests_remaining: int | None = Field(default=None, ge=0)
    below_soft_threshold: bool = Field(
        default=False,
        description="True when headroom_pct is under pool soft_gate_threshold_pct.",
    )


class RoutingContext(BaseModel):
    """Inputs for policy evaluation on a single routed request."""

    requested_model: str
    tenancy: TenancyContext = Field(default_factory=TenancyContext)
    capabilities: RequestCapabilities = Field(default_factory=RequestCapabilities)
    agent_id: str | None = None
    session_id: str | None = None
    conversation_fingerprint: str | None = None
    budget: BudgetSnapshot | None = None
    rate_limits: list[RateLimitSnapshot] = Field(default_factory=list)
    quota_headroom: list[QuotaHeadroom] = Field(
        default_factory=list,
        description="Per-credential quota headroom from inventory / CLIProxy quota-summary.",
    )
    pool_affinity_mode: str | None = Field(
        default=None,
        description="Logical pool affinity_mode: fill-first | quota-aware | round-robin.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = Field(
        default=False,
        description="When true, evaluate and return a decision without persisting affinity updates.",
    )

    @field_validator("requested_model")
    @classmethod
    def strip_model_prefix(cls, value: str) -> str:
        prefix = "AI-Gateway:"
        if value.startswith(prefix):
            return value[len(prefix) :]
        return value


class GateAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    THROTTLE = "throttle"


class RoutingDecision(BaseModel):
    """Policy output consumed by translator → LiteLLM metadata."""

    gate: GateAction = GateAction.ALLOW
    deny_reason: str | None = None
    retry_after_seconds: int | None = Field(default=None, ge=0)

    allowed_models: list[str] = Field(default_factory=list)
    fallback_chain: list[str] = Field(default_factory=list)
    ordered_deployments: list[str] = Field(default_factory=list)

    credential_tier_preference: str | None = None
    preferred_credential_id: str | None = None
    session_key: str | None = Field(
        default=None,
        description="Stable key forwarded to CLIProxy for session-affinity.",
    )

    lock_model_family: bool = False
    cache_cold_start: bool = False

    quota_aware_mode: bool = Field(
        default=False,
        description="When true, CLIProxy should use quota-aware affinity (pre-emptive 429 avoidance).",
    )
    deprioritized_credentials: list[str] = Field(
        default_factory=list,
        description="Credential IDs to skip — pre-emptive deprioritization before hard 429.",
    )

    policy_version: str = "v0-stub"
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rules_applied: list[str] = Field(default_factory=list)
    debug: dict[str, Any] = Field(default_factory=dict)

    def to_metadata(self) -> dict[str, Any]:
        """Serialize for injection into LiteLLM request metadata."""
        payload = self.model_dump(mode="json", exclude={"debug"})
        if not self.debug:
            payload.pop("debug", None)
        return payload


class EvaluateRequest(BaseModel):
    context: RoutingContext


class EvaluateResponse(BaseModel):
    decision: RoutingDecision


class PolicyProfile(BaseModel):
    """Row from policy_profiles (Epic #38, issue 38-5)."""

    profile_id: str
    scope: PolicyScope
    scope_id: str
    allowed_models: list[str] = Field(default_factory=list)
    denied_models: list[str] = Field(default_factory=list)
    fallback_chain_override: list[str] = Field(default_factory=list)
    credential_tier_preference: str | None = None
    policy_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class CredentialEvent(BaseModel):
    """Webhook payload from credential-prober on inventory status transitions."""

    credential_id: str
    provider: str | None = None
    previous_status: str
    new_status: str
    cool_down_until: datetime | None = None
    reason: str | None = None
    timestamp: datetime | None = Field(
        default=None,
        description="Event time for idempotent writes (credential_id + timestamp).",
    )


class CredentialEventResponse(BaseModel):
    accepted: bool = True


class HealthResponse(BaseModel):
    status: str = "ok"
    policy_version: str = "v0-stub"
