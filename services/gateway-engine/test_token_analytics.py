"""
Unit tests for token usage analytics (#117).
Tests token extraction and Prometheus metric recording for Translator responses.
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
        }
    ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
