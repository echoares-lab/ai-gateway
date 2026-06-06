from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    "translator_requests_total",
    "Total translator HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "translator_request_duration_seconds",
    "Translator request latency in seconds",
    ["method", "path"],
)
UPSTREAM_ERRORS = Counter(
    "translator_upstream_errors_total",
    "Translator upstream errors by path and status",
    ["path", "status"],
)
CACHE_HITS = Counter(
    "translator_cache_hits_total",
    "Translator cache hits",
    ["path", "kind"],
)
CACHE_MISSES = Counter(
    "translator_cache_misses_total",
    "Translator cache misses",
    ["path", "kind"],
)
FORMAT_REQUESTS = Counter(
    "translator_format_requests_total",
    "Requests by translated API format",
    ["format"],
)
IN_FLIGHT = Counter(
    "translator_in_flight_total",
    "Total requests entering translator middleware",
)

# ── Per-provider / per-model routing signals (issue #59) ──────────────────────
# Passive, in-traffic signals for adaptive routing (see docs/ADAPTIVE_ROUTING.md).
# Captured on every upstream LiteLLM call; never via active background probing.
PROVIDER_LATENCY = Histogram(
    "translator_provider_request_duration_seconds",
    "Upstream LiteLLM request latency by provider and model",
    ["provider", "model"],
)
PROVIDER_REQUESTS = Counter(
    "translator_provider_requests_total",
    "Upstream LiteLLM requests by provider, model, and outcome",
    ["provider", "model", "outcome"],
)
PROVIDER_RATE_LIMITS = Counter(
    "translator_provider_rate_limits_total",
    "Upstream 429 rate-limit responses by provider and model",
    ["provider", "model"],
)

# --- Token usage analytics (issue #117) ---
TOKEN_INPUT = Counter(
    "translator_token_input_total",
    "Total input tokens processed by provider and model",
    ["provider", "model"],
)
TOKEN_OUTPUT = Counter(
    "translator_token_output_total",
    "Total output tokens processed by provider and model",
    ["provider", "model"],
)
TOKEN_REQUESTS = Counter(
    "translator_token_requests_total",
    "Total requests with token data by provider and model",
    ["provider", "model"],
)
TOKEN_CANONICAL_INPUT = Counter(
    "translator_token_canonical_input_total",
    "Total input tokens processed by requested provider/model and canonical registry model",
    ["provider", "model", "canonical_model_id", "canonical_provider", "canonical_family"],
)
TOKEN_CANONICAL_OUTPUT = Counter(
    "translator_token_canonical_output_total",
    "Total output tokens processed by requested provider/model and canonical registry model",
    ["provider", "model", "canonical_model_id", "canonical_provider", "canonical_family"],
)
TOKEN_CANONICAL_REQUESTS = Counter(
    "translator_token_canonical_requests_total",
    "Total requests with token data by requested provider/model and canonical registry model",
    ["provider", "model", "canonical_model_id", "canonical_provider", "canonical_family"],
)
