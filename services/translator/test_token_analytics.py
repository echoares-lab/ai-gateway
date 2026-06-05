"""
Unit tests for token usage analytics (#117).
Tests token extraction and Prometheus metric recording for Translator responses.
"""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import translator


def test_record_token_usage_anthropic():
    """Test token extraction from Claude response format."""
    response = {
        "usage": {
            "prompt_tokens": 125,
            "completion_tokens": 42
        }
    }
    
    # Mock the Prometheus counters
    with patch.object(translator.TOKEN_INPUT, 'labels') as mock_input, \
         patch.object(translator.TOKEN_OUTPUT, 'labels') as mock_output, \
         patch.object(translator.TOKEN_REQUESTS, 'labels') as mock_requests:
        
        mock_input_counter = MagicMock()
        mock_output_counter = MagicMock()
        mock_requests_counter = MagicMock()
        
        mock_input.return_value = mock_input_counter
        mock_output.return_value = mock_output_counter
        mock_requests.return_value = mock_requests_counter
        
        translator._record_token_usage("claude-sonnet-4-6", response)
        
        # Verify metrics were recorded
        mock_input.assert_called_once_with("anthropic", "claude-sonnet-4-6")
        mock_input_counter.inc.assert_called_once_with(125)
        
        mock_output.assert_called_once_with("anthropic", "claude-sonnet-4-6")
        mock_output_counter.inc.assert_called_once_with(42)
        
        mock_requests.assert_called_once_with("anthropic", "claude-sonnet-4-6")
        mock_requests_counter.inc.assert_called_once()


def test_record_token_usage_openai():
    """Test token extraction from GPT response format."""
    response = {
        "usage": {
            "prompt_tokens": 250,
            "completion_tokens": 88
        }
    }
    
    with patch.object(translator.TOKEN_INPUT, 'labels') as mock_input, \
         patch.object(translator.TOKEN_OUTPUT, 'labels') as mock_output:
        
        mock_input_counter = MagicMock()
        mock_output_counter = MagicMock()
        
        mock_input.return_value = mock_input_counter
        mock_output.return_value = mock_output_counter
        
        translator._record_token_usage("gpt-5-4", response)
        
        mock_input.assert_called_once_with("openai", "gpt-5-4")
        mock_input_counter.inc.assert_called_once_with(250)
        
        mock_output.assert_called_once_with("openai", "gpt-5-4")
        mock_output_counter.inc.assert_called_once_with(88)


def test_record_token_usage_gemini():
    """Test token extraction from Gemini response format."""
    response = {
        "usage": {
            "prompt_tokens": 512,
            "completion_tokens": 156
        }
    }
    
    with patch.object(translator.TOKEN_INPUT, 'labels') as mock_input, \
         patch.object(translator.TOKEN_OUTPUT, 'labels') as mock_output:
        
        mock_input_counter = MagicMock()
        mock_output_counter = MagicMock()
        
        mock_input.return_value = mock_input_counter
        mock_output.return_value = mock_output_counter
        
        translator._record_token_usage("gemini-3-flash", response)
        
        mock_input.assert_called_once_with("google", "gemini-3-flash")
        mock_input_counter.inc.assert_called_once_with(512)
        
        mock_output.assert_called_once_with("google", "gemini-3-flash")
        mock_output_counter.inc.assert_called_once_with(156)


def test_record_token_usage_missing_usage():
    """Test graceful handling of missing usage data."""
    response = {"choices": [{"message": {"content": "Hello"}}]}
    
    # Should not raise an exception
    translator._record_token_usage("claude-sonnet-4-6", response)


def test_record_token_usage_malformed_response():
    """Test graceful handling of malformed responses."""
    with patch.object(translator.TOKEN_INPUT, 'labels') as mock_input:
        # Should not raise an exception even with invalid input
        translator._record_token_usage("claude-sonnet-4-6", None)
        translator._record_token_usage("claude-sonnet-4-6", "not a dict")
        translator._record_token_usage("claude-sonnet-4-6", {})
        
        # Metrics should not be called
        mock_input.assert_not_called()


def test_record_token_usage_zero_tokens():
    """Test that zero token counts are not recorded."""
    response = {
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0
        }
    }
    
    with patch.object(translator.TOKEN_INPUT, 'labels') as mock_input, \
         patch.object(translator.TOKEN_OUTPUT, 'labels') as mock_output, \
         patch.object(translator.TOKEN_REQUESTS, 'labels') as mock_requests:
        
        translator._record_token_usage("claude-sonnet-4-6", response)
        
        # Should not record metrics for zero tokens
        mock_input.assert_not_called()
        mock_output.assert_not_called()
        mock_requests.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
