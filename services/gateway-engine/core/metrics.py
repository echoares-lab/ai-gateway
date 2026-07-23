from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from prometheus_client import Counter, Gauge, Histogram

if TYPE_CHECKING:
    from core.model_registry import ModelRegistryRecord

REQUEST_COUNT = Counter(
    "gateway_engine_requests_total",
    "Total gateway-engine HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "gateway_engine_request_duration_seconds",
    "Gateway Engine request latency in seconds",
    ["method", "path"],
)
UPSTREAM_ERRORS = Counter(
    "gateway_engine_upstream_errors_total",
    "Gateway Engine upstream errors by path and status",
    ["path", "status"],
)
CACHE_HITS = Counter(
    "gateway_engine_cache_hits_total",
    "Gateway Engine cache hits",
    ["path", "kind"],
)
CACHE_MISSES = Counter(
    "gateway_engine_cache_misses_total",
    "Gateway Engine cache misses",
    ["path", "kind"],
)
FORMAT_REQUESTS = Counter(
    "gateway_engine_format_requests_total",
    "Requests by translated API format",
    ["format"],
)
IN_FLIGHT = Gauge(
    "gateway_engine_in_flight",
    "In-flight gateway-engine HTTP requests",
)

# Model reconciliation labels are deliberately finite. Requested model names,
# aliases, credentials, and error strings must never become metric labels.
MODEL_RECONCILIATION_RUNS = Counter(
    "gateway_engine_model_reconciliation_runs_total",
    "Completed model reconciliation runs by bounded outcome and trigger",
    ["outcome", "trigger"],
)
MODEL_RECONCILIATION_DURATION = Histogram(
    "gateway_engine_model_reconciliation_duration_seconds",
    "Model reconciliation run duration by bounded outcome and trigger",
    ["outcome", "trigger"],
)
MODEL_RECONCILIATION_CHANGES = Counter(
    "gateway_engine_model_reconciliation_changes_total",
    "Model reconciliation record counts by bounded change kind",
    ["change"],
)

_RECONCILIATION_OUTCOMES = frozenset({"success", "degraded", "failed"})
_RECONCILIATION_TRIGGERS = frozenset({"startup", "scheduled", "demand", "manual"})
_RECONCILIATION_CHANGES = ("discovered", "added", "updated", "enabled", "disabled", "unchanged")


def record_model_reconciliation(result: Any) -> None:
    """Record one result without accepting high-cardinality labels."""
    outcome_value = str(getattr(result, "outcome", ""))
    outcome = outcome_value if outcome_value in _RECONCILIATION_OUTCOMES else "unknown"
    raw_trigger = getattr(result, "trigger", "")
    trigger_value = str(getattr(raw_trigger, "value", raw_trigger))
    trigger = trigger_value if trigger_value in _RECONCILIATION_TRIGGERS else "unknown"
    started_at = getattr(result, "started_at", None)
    completed_at = getattr(result, "completed_at", None)
    duration = max(0.0, (completed_at - started_at).total_seconds()) if started_at and completed_at else 0.0

    MODEL_RECONCILIATION_RUNS.labels(outcome=outcome, trigger=trigger).inc()
    MODEL_RECONCILIATION_DURATION.labels(outcome=outcome, trigger=trigger).observe(duration)
    counts = getattr(result, "counts", {}) or {}
    for change in _RECONCILIATION_CHANGES:
        value = counts.get(change, 0)
        if isinstance(value, (int, float)) and value > 0:
            MODEL_RECONCILIATION_CHANGES.labels(change=change).inc(value)


MODEL_ABSENT = Gauge(
    "gateway_model_absent",
    "Model missing from latest CLIProxy discovery",
    ["model_id", "family"],
)
MODEL_ABSENT_DAYS = Gauge(
    "gateway_model_absent_days",
    "Days since continuous discovery absence began",
    ["model_id", "family"],
)
MODEL_ADVERTISED = Gauge(
    "gateway_model_advertised",
    "Model advertised in live catalog",
    ["model_id", "family"],
)
MODEL_RETIRED = Gauge(
    "gateway_model_retired",
    "Model retired (kept in registry, not advertised)",
    ["model_id", "family"],
)

_LIFECYCLE_GAUGES = (MODEL_ABSENT, MODEL_ABSENT_DAYS, MODEL_ADVERTISED, MODEL_RETIRED)
_last_lifecycle_labels: set[tuple[str, str]] = set()


def record_model_lifecycle(models: list[ModelRegistryRecord]) -> None:
    """Export per-model lifecycle gauges after a successful registry persist."""
    from core.model_registry import ModelRegistryRecord as _ModelRegistryRecord

    now = datetime.now(timezone.utc)
    current_labels: set[tuple[str, str]] = set()
    for model in models:
        if not isinstance(model, _ModelRegistryRecord):
            continue
        label_key = (model.model_id, model.family)
        current_labels.add(label_key)
        labels = {"model_id": model.model_id, "family": model.family}
        absent = 1.0 if model.absent_since is not None else 0.0
        absent_days = 0.0
        if model.absent_since is not None:
            absent_days = max(0.0, (now - model.absent_since).total_seconds() / 86400.0)
        MODEL_ABSENT.labels(**labels).set(absent)
        MODEL_ABSENT_DAYS.labels(**labels).set(absent_days)
        MODEL_ADVERTISED.labels(**labels).set(1.0 if model.advertised else 0.0)
        MODEL_RETIRED.labels(**labels).set(1.0 if model.retired else 0.0)

    stale_labels = _last_lifecycle_labels - current_labels
    for model_id, family in stale_labels:
        labels = {"model_id": model_id, "family": family}
        for gauge in _LIFECYCLE_GAUGES:
            gauge.labels(**labels).set(0)
    _last_lifecycle_labels.clear()
    _last_lifecycle_labels.update(current_labels)


# ── Per-provider / per-model routing signals (issue #59) ──────────────────────
# Passive, in-traffic signals for adaptive routing (see docs/ADAPTIVE_ROUTING.md).
# Captured on every upstream LiteLLM call; never via active background probing.
PROVIDER_LATENCY = Histogram(
    "gateway_engine_provider_request_duration_seconds",
    "Upstream LiteLLM request latency by provider and model",
    ["provider", "model"],
)
PROVIDER_REQUESTS = Counter(
    "gateway_engine_provider_requests_total",
    "Upstream LiteLLM requests by provider, model, and outcome",
    ["provider", "model", "outcome"],
)
PROVIDER_RATE_LIMITS = Counter(
    "gateway_engine_provider_rate_limits_total",
    "Upstream 429 rate-limit responses by provider and model",
    ["provider", "model"],
)

# --- Token usage analytics (issue #117) ---
TOKEN_INPUT = Counter(
    "gateway_engine_token_input_total",
    "Total input tokens processed by provider and model",
    ["provider", "model"],
)
TOKEN_OUTPUT = Counter(
    "gateway_engine_token_output_total",
    "Total output tokens processed by provider and model",
    ["provider", "model"],
)
TOKEN_REQUESTS = Counter(
    "gateway_engine_token_requests_total",
    "Total requests with token data by provider and model",
    ["provider", "model"],
)
TOKEN_CANONICAL_INPUT = Counter(
    "gateway_engine_token_canonical_input_total",
    "Total input tokens processed by requested provider/model and canonical registry model",
    ["provider", "model", "canonical_model_id", "canonical_provider", "canonical_family"],
)
TOKEN_CANONICAL_OUTPUT = Counter(
    "gateway_engine_token_canonical_output_total",
    "Total output tokens processed by requested provider/model and canonical registry model",
    ["provider", "model", "canonical_model_id", "canonical_provider", "canonical_family"],
)
TOKEN_CANONICAL_REQUESTS = Counter(
    "gateway_engine_token_canonical_requests_total",
    "Total requests with token data by requested provider/model and canonical registry model",
    ["provider", "model", "canonical_model_id", "canonical_provider", "canonical_family"],
)

# --- Token cache analytics ---
TOKEN_CACHE_INPUT = Counter(
    "gateway_engine_token_cache_input_total",
    "Total input tokens served from cache by provider, model, and cache type",
    ["provider", "model", "cache_type"],  # cache_type: gateway, litellm, provider
)
TOKEN_CACHE_OUTPUT = Counter(
    "gateway_engine_token_cache_output_total",
    "Total output tokens served from cache by provider, model, and cache type",
    ["provider", "model", "cache_type"],  # cache_type: gateway, litellm, provider
)
TOKEN_CACHE_CANONICAL_INPUT = Counter(
    "gateway_engine_token_cache_canonical_input_total",
    "Total input tokens served from cache by requested provider/model, canonical registry model, and cache type",
    ["provider", "model", "canonical_model_id", "canonical_provider", "canonical_family", "cache_type"],
)
TOKEN_CACHE_CANONICAL_OUTPUT = Counter(
    "gateway_engine_token_cache_canonical_output_total",
    "Total output tokens served from cache by requested provider/model, canonical registry model, and cache type",
    ["provider", "model", "canonical_model_id", "canonical_provider", "canonical_family", "cache_type"],
)

# --- Extended Telemetry: Reasoning, Prompt Cache & TTFT ---
TOKEN_REASONING = Counter(
    "gateway_engine_token_reasoning_total",
    "Total reasoning/thinking tokens by provider, model, and effort level",
    ["provider", "model", "effort_level"],
)
TOKEN_PROMPT_CACHE_CREATED = Counter(
    "gateway_engine_prompt_cache_created_tokens_total",
    "Total prompt tokens written into upstream cache by provider and model",
    ["provider", "model"],
)
TOKEN_PROMPT_CACHE_READ = Counter(
    "gateway_engine_prompt_cache_read_tokens_total",
    "Total prompt tokens read from upstream cache by provider and model",
    ["provider", "model"],
)
TIME_TO_FIRST_TOKEN = Histogram(
    "gateway_engine_time_to_first_token_seconds",
    "Streaming response time-to-first-token in seconds by provider and model",
    ["provider", "model"],
)
