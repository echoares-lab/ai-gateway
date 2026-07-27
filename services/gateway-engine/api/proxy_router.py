"""Thin facade: deps, router registration, and re-exports for main.py."""

from __future__ import annotations

from api import proxy_catchall as _proxy_catchall  # noqa: F401

# Side-effect imports register routes on the shared router.
# Catch-all MUST be last so /{path:path} does not shadow specific routes.
from api import proxy_claude as _proxy_claude  # noqa: F401
from api import proxy_gemini as _proxy_gemini  # noqa: F401
from api import proxy_responses as _proxy_responses  # noqa: F401
from api.proxy_catchall import proxy  # noqa: F401
from api.proxy_claude import (  # noqa: F401
    _claude_msg_to_oai,
    _claude_req_to_oai,
    _oai_to_claude_resp,
    _oai_to_claude_stream,
    claude_proxy,
)
from api.proxy_common import (  # noqa: F401
    ProxyRouterDeps,
    _aiter_list,
    _deps,
    _enable_virtual_providers,
    _http_client,
    _main_override,
    _tee_lines,
    configure_proxy_routes,
    log,
    router,
)
from api.proxy_gemini import (  # noqa: F401
    GEMINI_FINISH_MAP,
    _find_tool_call_id_in_history,
    _gemini_req_to_oai,
    _gemini_stream,
    _get_gemini_map,
    _oai_to_gemini_resp,
    gemini_proxy,
)
from api.proxy_normalize import (  # noqa: F401
    _add_prefix_to_models_response,
    _normalize_content,
    _normalize_content_item,
    _normalize_messages,
    _normalize_model,
    _normalize_tools,
    _patch_body,
    _resolve_model,
    _ResolvedModel,
    _responses_input_to_messages,
    _strip_prefix,
)
from api.proxy_responses import (  # noqa: F401
    _oai_to_responses_resp,
    _oai_to_responses_stream,
    _responses_req_to_oai,
    _sse,
    responses_proxy,
)
from api.proxy_routing import (  # noqa: F401
    _apply_policy_engine,
    _auth_fingerprint,
    _build_routing_context,
    _evaluate_policy_engine,
    _extract_and_apply_tenancy,
    _model_from_content,
    _model_registry_metadata_for_policy,
    _normalize_upstream_authorization,
    _outcome_for_status,
    _post_with_retry,
    _provider_of,
    _quota_headroom_cache,
    _record_cached_token_usage,
    _record_provider_signal,
    _record_token_usage,
    _tenancy_from_token,
    is_unknown_model_response,
    maybe_enqueue_unknown_model_refresh,
)
from core.metrics import (  # noqa: F401
    PROVIDER_LATENCY,
    PROVIDER_RATE_LIMITS,
    PROVIDER_REQUESTS,
    TOKEN_CACHE_CANONICAL_INPUT,
    TOKEN_CACHE_CANONICAL_OUTPUT,
    TOKEN_CACHE_INPUT,
    TOKEN_CACHE_OUTPUT,
    TOKEN_CANONICAL_INPUT,
    TOKEN_CANONICAL_OUTPUT,
    TOKEN_CANONICAL_REQUESTS,
    TOKEN_INPUT,
    TOKEN_OUTPUT,
    TOKEN_REQUESTS,
)

# Catch-all must be registered after specific routes so it does not shadow them.
router.add_api_route(
    "/{path:path}",
    proxy,
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
