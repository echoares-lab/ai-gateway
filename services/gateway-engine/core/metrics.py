from prometheus_client import Counter, Gauge, Histogram

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
