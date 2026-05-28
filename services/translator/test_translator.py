"""
Unit tests for translator.py.

Run inside the container:
  docker compose exec translator pytest test_translator.py -v

Or locally if deps are installed:
  pytest services/translator/test_translator.py -v
"""
import asyncio
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inline-import the module under test.  translator.py lives next to this file
# when running inside the container; on the host we add the directory to sys.path.
# ---------------------------------------------------------------------------
import os
sys.path.insert(0, os.path.dirname(__file__))
import translator as t


# ===========================================================================
# _normalize_content_item
# ===========================================================================

class TestNormalizeContentItem(unittest.TestCase):
    def test_input_text(self):
        result = t._normalize_content_item({"type": "input_text", "text": "hello"})
        assert result == {"type": "text", "text": "hello"}

    def test_output_text(self):
        result = t._normalize_content_item({"type": "output_text", "text": "world"})
        assert result == {"type": "text", "text": "world"}

    def test_text_passthrough(self):
        result = t._normalize_content_item({"type": "text", "text": "direct"})
        assert result == {"type": "text", "text": "direct"}

    def test_refusal(self):
        result = t._normalize_content_item({"type": "refusal", "refusal": "I can't do that"})
        assert result == {"type": "text", "text": "I can't do that"}

    def test_input_image_url_string(self):
        result = t._normalize_content_item({
            "type": "input_image",
            "image_url": "https://example.com/img.png",
        })
        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == "https://example.com/img.png"

    def test_input_image_url_object(self):
        result = t._normalize_content_item({
            "type": "input_image",
            "url": "https://example.com/img.png",
            "detail": "high",
        })
        assert result["type"] == "image_url"
        assert result["image_url"]["detail"] == "high"

    def test_input_image_base64_source(self):
        result = t._normalize_content_item({
            "type": "input_image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": "abc123",
            },
        })
        assert result["type"] == "image_url"
        assert result["image_url"]["url"].startswith("data:image/png;base64,")

    def test_input_file(self):
        result = t._normalize_content_item({"type": "input_file", "filename": "doc.pdf"})
        assert result["type"] == "text"
        assert "doc.pdf" in result["text"]

    def test_unknown_type_passthrough(self):
        item = {"type": "unknown_type", "data": 42}
        result = t._normalize_content_item(item)
        assert result == item


# ===========================================================================
# _normalize_content
# ===========================================================================

class TestNormalizeContent(unittest.TestCase):
    def test_string_passthrough(self):
        assert t._normalize_content("hello") == "hello"

    def test_none_passthrough(self):
        assert t._normalize_content(None) is None

    def test_all_text_items_collapse_to_string(self):
        result = t._normalize_content([
            {"type": "text", "text": "foo"},
            {"type": "text", "text": "bar"},
        ])
        assert result == "foobar"

    def test_mixed_items_stay_as_list(self):
        result = t._normalize_content([
            {"type": "text", "text": "caption"},
            {"type": "image_url", "image_url": {"url": "https://x.com/img.png"}},
        ])
        assert isinstance(result, list)
        assert len(result) == 2


# ===========================================================================
# _strip_prefix / _add_prefix_to_models_response
# ===========================================================================

class TestModelPrefix(unittest.TestCase):
    def test_strip_prefix_present(self):
        body = json.dumps({"model": "AI-Gateway:claude-sonnet-4-6", "messages": []}).encode()
        result, changed = t._strip_prefix(body)
        assert changed
        assert json.loads(result)["model"] == "claude-sonnet-4-6"

    def test_strip_prefix_absent(self):
        body = json.dumps({"model": "claude-sonnet-4-6", "messages": []}).encode()
        result, changed = t._strip_prefix(body)
        assert not changed
        assert result == body

    def test_strip_prefix_invalid_json(self):
        result, changed = t._strip_prefix(b"not json")
        assert not changed

    def test_add_prefix_to_models_response(self):
        body = json.dumps({"data": [{"id": "claude-sonnet-4-6"}, {"id": "gpt-5"}]}).encode()
        result = t._add_prefix_to_models_response(body)
        ids = [m["id"] for m in json.loads(result)["data"]]
        assert all(i.startswith("AI-Gateway:") for i in ids)

    def test_add_prefix_idempotent(self):
        body = json.dumps({"data": [{"id": "AI-Gateway:claude-sonnet-4-6"}]}).encode()
        result = t._add_prefix_to_models_response(body)
        ids = [m["id"] for m in json.loads(result)["data"]]
        assert ids[0].count("AI-Gateway:") == 1


# ===========================================================================
# _normalize_tools
# ===========================================================================

class TestNormalizeTools(unittest.TestCase):
    def test_responses_format_converted(self):
        """Responses API tool {type, name, parameters} → Chat Completions {type, function: {...}}"""
        tools = [{"type": "function", "name": "search", "parameters": {"q": "str"}}]
        result, changed = t._normalize_tools(tools)
        assert changed
        assert result[0]["function"]["name"] == "search"
        assert result[0]["function"]["parameters"] == {"q": "str"}

    def test_already_chat_completions_format_unchanged(self):
        tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
        result, changed = t._normalize_tools(tools)
        assert not changed
        assert result == tools


# ===========================================================================
# _patch_body
# ===========================================================================

class TestPatchBody(unittest.TestCase):
    def test_responses_api_input_converted_to_messages(self):
        body = json.dumps({
            "model": "gpt-5",
            "input": "Hello, world",
        }).encode()
        result, changed = t._patch_body("v1/chat/completions", body)
        assert changed
        data = json.loads(result)
        assert "messages" in data
        assert data["messages"][0]["content"] == "Hello, world"

    def test_non_chat_completions_path_unchanged(self):
        body = json.dumps({"model": "gpt-5", "input": "x"}).encode()
        result, changed = t._patch_body("v1/models", body)
        assert not changed
        assert result == body

    def test_tools_normalized_in_patch_body(self):
        body = json.dumps({
            "model": "gpt-5",
            "messages": [{"role": "user", "content": "hi"}],
            "tools": [{"type": "function", "name": "search", "parameters": {}}],
        }).encode()
        result, changed = t._patch_body("v1/chat/completions", body)
        assert changed
        data = json.loads(result)
        assert "function" in data["tools"][0]


# ===========================================================================
# _responses_input_to_messages
# ===========================================================================

class TestResponsesInputToMessages(unittest.TestCase):
    def test_string_input(self):
        msgs = t._responses_input_to_messages("hello")
        assert msgs == [{"role": "user", "content": "hello"}]

    def test_list_with_message_item(self):
        inp = [{"type": "message", "role": "user", "content": "question"}]
        msgs = t._responses_input_to_messages(inp)
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "question"

    def test_function_call_output_produces_tool_message(self):
        inp = [
            {"type": "function_call", "call_id": "call_1", "name": "search", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call_1", "output": '{"result": "ok"}'},
        ]
        msgs = t._responses_input_to_messages(inp)
        roles = [m["role"] for m in msgs]
        assert "assistant" in roles
        assert "tool" in roles


# ===========================================================================
# _post_with_retry  (async)
# ===========================================================================

@pytest.mark.asyncio
async def test_post_with_retry_success_on_first_attempt():
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("translator.httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await t._post_with_retry("http://litellm:4000/v1/chat/completions", {}, b"{}")

    assert result.status_code == 200
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_post_with_retry_retries_on_502():
    ok_resp = MagicMock()
    ok_resp.status_code = 200

    err_resp = MagicMock()
    err_resp.status_code = 502

    call_count = 0

    async def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return err_resp
        return ok_resp

    mock_client = AsyncMock()
    mock_client.post = fake_post

    with patch("translator.httpx.AsyncClient") as MockClient, \
         patch("translator.asyncio.sleep", new=AsyncMock()):
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await t._post_with_retry("http://litellm:4000/v1/chat/completions", {}, b"{}", retries=1)

    assert result.status_code == 200
    assert call_count == 2


@pytest.mark.asyncio
async def test_post_with_retry_stops_after_retries_exhausted():
    err_resp = MagicMock()
    err_resp.status_code = 503

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=err_resp)

    with patch("translator.httpx.AsyncClient") as MockClient, \
         patch("translator.asyncio.sleep", new=AsyncMock()):
        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await t._post_with_retry("http://litellm:4000/v1/chat/completions", {}, b"{}", retries=2)

    assert result.status_code == 503
    # 1 initial + 2 retries = 3 calls
    assert mock_client.post.call_count == 3
