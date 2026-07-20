"""
Unit tests for token usage analytics (#117).
Tests token extraction and Prometheus metric recording for Gateway Engine responses.
"""

from unittest.mock import MagicMock, patch

import main
import pytest


def test_record_token_usage_anthropic():
    """Test token extraction from Claude response format."""
    response = {"usage": {"prompt_tokens": 125, "completion_tokens": 42}}

    # Mock the Prometheus counters
    with (
        patch.object(main.TOKEN_INPUT, "labels") as mock_input,
        patch.object(main.TOKEN_OUTPUT, "labels") as mock_output,
        patch.object(main.TOKEN_REQUESTS, "labels") as mock_requests,
    ):
        mock_input_counter = MagicMock()
        mock_output_counter = MagicMock()
        mock_requests_counter = MagicMock()

        mock_input.return_value = mock_input_counter
        mock_output.return_value = mock_output_counter
        mock_requests.return_value = mock_requests_counter

        main._record_token_usage("claude-sonnet-4-6", response)

        # Verify metrics were recorded
        mock_input.assert_called_once_with("anthropic", "claude-sonnet-4-6")
        mock_input_counter.inc.assert_called_once_with(125)

        mock_output.assert_called_once_with("anthropic", "claude-sonnet-4-6")
        mock_output_counter.inc.assert_called_once_with(42)

        mock_requests.assert_called_once_with("anthropic", "claude-sonnet-4-6")
        mock_requests_counter.inc.assert_called_once()


def test_record_token_usage_openai():
    """Test token extraction from GPT response format."""
    response = {"usage": {"prompt_tokens": 250, "completion_tokens": 88}}

    with (
        patch.object(main.TOKEN_INPUT, "labels") as mock_input,
        patch.object(main.TOKEN_OUTPUT, "labels") as mock_output,
    ):
        mock_input_counter = MagicMock()
        mock_output_counter = MagicMock()

        mock_input.return_value = mock_input_counter
        mock_output.return_value = mock_output_counter

        main._record_token_usage("gpt-5-4", response)

        mock_input.assert_called_once_with("openai", "gpt-5-4")
        mock_input_counter.inc.assert_called_once_with(250)

        mock_output.assert_called_once_with("openai", "gpt-5-4")
        mock_output_counter.inc.assert_called_once_with(88)


def test_record_token_usage_gemini():
    """Test token extraction from Gemini response format."""
    response = {"usage": {"prompt_tokens": 512, "completion_tokens": 156}}

    with (
        patch.object(main.TOKEN_INPUT, "labels") as mock_input,
        patch.object(main.TOKEN_OUTPUT, "labels") as mock_output,
    ):
        mock_input_counter = MagicMock()
        mock_output_counter = MagicMock()

        mock_input.return_value = mock_input_counter
        mock_output.return_value = mock_output_counter

        main._record_token_usage("gemini-3-flash", response)

        mock_input.assert_called_once_with("google", "gemini-3-flash")
        mock_input_counter.inc.assert_called_once_with(512)

        mock_output.assert_called_once_with("google", "gemini-3-flash")
        mock_output_counter.inc.assert_called_once_with(156)


def test_record_token_usage_emits_canonical_registry_metrics():
    response = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    registry_metadata = {
        "canonical_model_id": "claude-sonnet-4-6",
        "provider": "anthropic",
        "family": "claude",
    }

    with (
        patch.object(main, "_model_registry_metadata_for_policy", return_value=registry_metadata),
        patch.object(main.TOKEN_INPUT, "labels") as mock_input,
        patch.object(main.TOKEN_OUTPUT, "labels") as mock_output,
        patch.object(main.TOKEN_REQUESTS, "labels") as mock_requests,
        patch.object(main.TOKEN_CANONICAL_INPUT, "labels") as mock_canonical_input,
        patch.object(main.TOKEN_CANONICAL_OUTPUT, "labels") as mock_canonical_output,
        patch.object(main.TOKEN_CANONICAL_REQUESTS, "labels") as mock_canonical_requests,
    ):
        main._record_token_usage("sonnet", response)

        mock_input.assert_called_once_with("unknown", "sonnet")
        mock_output.assert_called_once_with("unknown", "sonnet")
        mock_requests.assert_called_once_with("unknown", "sonnet")
        mock_canonical_input.assert_called_once_with(
            "unknown",
            "sonnet",
            "claude-sonnet-4-6",
            "anthropic",
            "claude",
        )
        mock_canonical_input.return_value.inc.assert_called_once_with(10)
        mock_canonical_output.assert_called_once_with(
            "unknown",
            "sonnet",
            "claude-sonnet-4-6",
            "anthropic",
            "claude",
        )
        mock_canonical_output.return_value.inc.assert_called_once_with(5)
        mock_canonical_requests.assert_called_once_with(
            "unknown",
            "sonnet",
            "claude-sonnet-4-6",
            "anthropic",
            "claude",
        )
        mock_canonical_requests.return_value.inc.assert_called_once()


def test_record_token_usage_missing_usage():
    """Test graceful handling of missing usage data."""
    response = {"choices": [{"message": {"content": "Hello"}}]}

    # Should not raise an exception
    main._record_token_usage("claude-sonnet-4-6", response)


def test_record_token_usage_malformed_response():
    """Test graceful handling of malformed responses."""
    with patch.object(main.TOKEN_INPUT, "labels") as mock_input:
        # Should not raise an exception even with invalid input
        main._record_token_usage("claude-sonnet-4-6", None)
        main._record_token_usage("claude-sonnet-4-6", "not a dict")
        main._record_token_usage("claude-sonnet-4-6", {})

        # Metrics should not be called
        mock_input.assert_not_called()


def test_record_token_usage_zero_tokens():
    """Test that zero token counts are not recorded."""
    response = {"usage": {"prompt_tokens": 0, "completion_tokens": 0}}

    with (
        patch.object(main.TOKEN_INPUT, "labels") as mock_input,
        patch.object(main.TOKEN_OUTPUT, "labels") as mock_output,
        patch.object(main.TOKEN_REQUESTS, "labels") as mock_requests,
    ):
        main._record_token_usage("claude-sonnet-4-6", response)

        # Should not record metrics for zero tokens
        mock_input.assert_not_called()
        mock_output.assert_not_called()
        mock_requests.assert_not_called()


def test_admin_token_analytics_rolls_up_canonical_model_ids():
    metrics_text = "\n".join(
        [
            'gateway_engine_token_input_total{provider="unknown",model="sonnet"} 10.0',
            'gateway_engine_token_output_total{provider="unknown",model="sonnet"} 5.0',
            'gateway_engine_token_input_total{provider="anthropic",model="claude-sonnet-4-6"} 3.0',
            'gateway_engine_token_output_total{provider="anthropic",model="claude-sonnet-4-6"} 2.0',
            (
                'gateway_engine_token_canonical_input_total{provider="unknown",model="sonnet",'
                'canonical_model_id="claude-sonnet-4-6",canonical_provider="anthropic",'
                'canonical_family="claude"} 10.0'
            ),
            (
                'gateway_engine_token_canonical_output_total{provider="unknown",model="sonnet",'
                'canonical_model_id="claude-sonnet-4-6",canonical_provider="anthropic",'
                'canonical_family="claude"} 5.0'
            ),
            (
                'gateway_engine_token_canonical_input_total{provider="anthropic",model="claude-sonnet-4-6",'
                'canonical_model_id="claude-sonnet-4-6",canonical_provider="anthropic",'
                'canonical_family="claude"} 3.0'
            ),
            (
                'gateway_engine_token_canonical_output_total{provider="anthropic",model="claude-sonnet-4-6",'
                'canonical_model_id="claude-sonnet-4-6",canonical_provider="anthropic",'
                'canonical_family="claude"} 2.0'
            ),
        ]
    )

    panel = main._admin_token_analytics_panel(metrics_text, [])

    assert panel["data"]["summary"]["total_tokens"] == 20
    canonical = panel["data"]["by_canonical_model"]
    assert canonical == [
        {
            "canonical_model_id": "claude-sonnet-4-6",
            "canonical_provider": "anthropic",
            "canonical_family": "claude",
            "requested_models": ["claude-sonnet-4-6", "sonnet"],
            "input_tokens": 13,
            "output_tokens": 7,
            "total_tokens": 20,
            "non_cached_input_tokens": 13,
            "non_cached_output_tokens": 7,
            "non_cached_tokens": 20,
            "cached_input_tokens": 0,
            "cached_output_tokens": 0,
            "cached_tokens": 0,
        }
    ]


def test_record_cached_token_usage_gateway():
    """Test recording tokens served from the gateway-engine local cache."""
    response = {"usage": {"prompt_tokens": 100, "completion_tokens": 25}}

    with (
        patch.object(main.TOKEN_CACHE_INPUT, "labels") as mock_input,
        patch.object(main.TOKEN_CACHE_OUTPUT, "labels") as mock_output,
    ):
        mock_input_counter = MagicMock()
        mock_output_counter = MagicMock()
        mock_input.return_value = mock_input_counter
        mock_output.return_value = mock_output_counter

        main._record_cached_token_usage("gpt-4", response, "gateway")

        mock_input.assert_called_once_with("openai", "gpt-4", "gateway")
        mock_input_counter.inc.assert_called_once_with(100)

        mock_output.assert_called_once_with("openai", "gpt-4", "gateway")
        mock_output_counter.inc.assert_called_once_with(25)


def test_record_token_usage_litellm_cache():
    """Test that LiteLLM cache hits increment cache metrics instead of raw metrics."""
    response = {"usage": {"prompt_tokens": 80, "completion_tokens": 15}}
    headers = {"x-litellm-cache": "HIT"}

    with (
        patch.object(main.TOKEN_INPUT, "labels") as mock_raw_input,
        patch.object(main.TOKEN_CACHE_INPUT, "labels") as mock_cache_input,
        patch.object(main.TOKEN_CACHE_OUTPUT, "labels") as mock_cache_output,
    ):
        mock_raw_input_counter = MagicMock()
        mock_cache_input_counter = MagicMock()
        mock_cache_output_counter = MagicMock()

        mock_raw_input.return_value = mock_raw_input_counter
        mock_cache_input.return_value = mock_cache_input_counter
        mock_cache_output.return_value = mock_cache_output_counter

        main._record_token_usage("gpt-4", response, headers)

        # Raw non-cache counters should not be touched
        mock_raw_input.assert_not_called()

        # Cache counters should record the tokens under 'litellm' type
        mock_cache_input.assert_called_once_with("openai", "gpt-4", "litellm")
        mock_cache_input_counter.inc.assert_called_once_with(80)

        mock_cache_output.assert_called_once_with("openai", "gpt-4", "litellm")
        mock_cache_output_counter.inc.assert_called_once_with(15)


def test_record_token_usage_provider_prompt_cache():
    """Test that provider prompt cache hits are recorded under both raw and provider cache metrics."""
    response = {
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "prompt_tokens_details": {"cached_tokens": 600},
        }
    }

    with (
        patch.object(main.TOKEN_INPUT, "labels") as mock_raw_input,
        patch.object(main.TOKEN_CACHE_INPUT, "labels") as mock_cache_input,
    ):
        mock_raw_input_counter = MagicMock()
        mock_cache_input_counter = MagicMock()

        mock_raw_input.return_value = mock_raw_input_counter
        mock_cache_input.return_value = mock_cache_input_counter

        main._record_token_usage("claude-3-5", response)

        # Raw total tokens must still be counted
        mock_raw_input.assert_called_once_with("anthropic", "claude-3-5")
        mock_raw_input_counter.inc.assert_called_once_with(1000)

        # Sub-segment of tokens matching provider-side cache must be recorded
        mock_cache_input.assert_called_once_with("anthropic", "claude-3-5", "provider")
        mock_cache_input_counter.inc.assert_called_once_with(600)


def test_admin_token_analytics_includes_cache_metrics():
    """Test that the analytics panel aggregates and reports cache-related token values."""
    metrics_text = "\n".join(
        [
            'gateway_engine_token_input_total{provider="openai",model="gpt-4"} 100.0',
            'gateway_engine_token_output_total{provider="openai",model="gpt-4"} 20.0',
            'gateway_engine_token_cache_input_total{provider="openai",model="gpt-4",cache_type="gateway"} 50.0',
            'gateway_engine_token_cache_output_total{provider="openai",model="gpt-4",cache_type="gateway"} 10.0',
            'gateway_engine_token_cache_input_total{provider="openai",model="gpt-4",cache_type="litellm"} 30.0',
            'gateway_engine_token_cache_output_total{provider="openai",model="gpt-4",cache_type="litellm"} 5.0',
            'gateway_engine_token_cache_input_total{provider="openai",model="gpt-4",cache_type="provider"} 10.0',
        ]
    )

    panel = main._admin_token_analytics_panel(metrics_text, [])

    summary = panel["data"]["summary"]
    # Total input: 100 (non-cached) + 50 (gateway cache) + 30 (litellm cache) = 180
    assert summary["total_input_tokens"] == 180
    # Total output: 20 (non-cached) + 10 (gateway) + 5 (litellm) = 35
    assert summary["total_output_tokens"] == 35
    assert summary["total_tokens"] == 215

    # Cached totals
    assert summary["cached_input_tokens"] == 90  # 50 + 30 + 10 (provider cache)
    assert summary["cached_output_tokens"] == 15  # 10 + 5
    assert summary["cached_tokens"] == 105

    # Non-cached totals
    assert summary["non_cached_input_tokens"] == 100
    assert summary["non_cached_output_tokens"] == 20
    assert summary["non_cached_tokens"] == 120

    # Cache ratio: 105 / 215 * 100 = 48.84
    assert summary["cache_ratio_pct"] == 48.84

    # Cache type breakdown
    assert summary["by_cache_type"]["gateway"]["input_tokens"] == 50
    assert summary["by_cache_type"]["gateway"]["total_tokens"] == 60
    assert summary["by_cache_type"]["litellm"]["input_tokens"] == 30
    assert summary["by_cache_type"]["litellm"]["total_tokens"] == 35
    assert summary["by_cache_type"]["provider"]["input_tokens"] == 10
    assert summary["by_cache_type"]["provider"]["total_tokens"] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
