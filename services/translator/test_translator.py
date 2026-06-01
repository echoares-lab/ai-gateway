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

    with patch.object(t, "_client", mock_client):
        result = await t._post_with_retry("http://litellm:4000/v1/chat/completions", {}, b"{}")

    assert result.status_code == 200
    assert mock_client.post.call_count == 1


class TestGeminiReqToOai(unittest.TestCase):
    """_gemini_req_to_oai model name normalisation."""

    def _call(self, model, body=None, gemini_map=None):
        body = body or {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
        gmap = gemini_map or {}
        with patch.object(t, "_get_gemini_map", return_value=gmap):
            return t._gemini_req_to_oai(model, body)

    def test_customtools_suffix_stripped(self):
        oai = self._call("gemini-3.1-pro-preview-customtools",
                         gemini_map={"gemini-3.1-pro-preview": "gemini-3-1-pro-preview"})
        assert oai["model"] == "gemini-3-1-pro-preview"

    def test_base_model_unchanged_when_no_suffix(self):
        oai = self._call("gemini-3.1-pro-preview",
                         gemini_map={"gemini-3.1-pro-preview": "gemini-3-1-pro-preview"})
        assert oai["model"] == "gemini-3-1-pro-preview"

    def test_unknown_model_passthrough(self):
        oai = self._call("some-unknown-model")
        assert oai["model"] == "some-unknown-model"

    def test_customtools_on_unknown_model_stripped_to_base(self):
        oai = self._call("some-model-customtools")
        assert oai["model"] == "some-model"

    def test_unknown_preview_with_tools_falls_back_to_base(self):
        body = {
            "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            "tools": [{"functionDeclarations": [{"name": "search"}]}],
        }
        oai = self._call("gemini-2.5-pro-preview-05-06", body=body, gemini_map={})
        assert oai["model"] == "gemini-2.5-pro"

    def test_function_call_deterministic_id(self):
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": "hi"}]},
                {"role": "model", "parts": [{"functionCall": {"name": "read_file", "args": {"path": "a.txt"}}}]},
            ]
        }
        oai = self._call("gemini-3.0-pro", body=body)
        tool_calls = oai["messages"][1]["tool_calls"]
        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "read_file"
        assert tool_calls[0]["id"].startswith("call_")
        assert len(tool_calls[0]["id"]) == 25  # "call_" + 20 chars

    def test_function_response_deterministic_id_resolution(self):
        body = {
            "contents": [
                {"role": "user", "parts": [{"text": "hi"}]},
                {"role": "model", "parts": [{"functionCall": {"name": "read_file", "args": {"path": "a.txt"}}}]},
                {"role": "user", "parts": [{"functionResponse": {"name": "read_file", "response": {"content": "ok"}}}]},
            ]
        }
        oai = self._call("gemini-3.0-pro", body=body)
        messages = oai["messages"]
        # Assistant tool call ID should perfectly match the Tool response tool_call_id
        assistant_id = messages[1]["tool_calls"][0]["id"]
        tool_response_id = messages[2]["tool_call_id"]
        assert assistant_id == tool_response_id
        assert tool_response_id.startswith("call_")

    def test_generic_tool_call_id_resolution_openai_format(self):
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "tool_calls": [{"id": "custom_call_999", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}]},
        ]
        resolved_id = t._find_tool_call_id_in_history(history, "read_file", 2)
        assert resolved_id == "custom_call_999"


def test_responses_preview_model_warns_and_passthrough(caplog):
    caplog.set_level("WARNING")
    oai = t._responses_req_to_oai({"model": "foo-preview", "input": "hello"})
    assert oai["model"] == "foo-preview"
    assert any("model_resolution" in r.message and "preview_passthrough" in r.message for r in caplog.records)


def test_patch_body_model_resolution_from_dotted_name():
    body = json.dumps({"model": "gemini.3.1.pro", "messages": [{"role": "user", "content": "x"}]}).encode()
    result, changed = t._patch_body("v1/chat/completions", body)
    assert changed
    assert json.loads(result)["model"] == "gemini-3-1-pro"


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

    with patch.object(t, "_client", mock_client), \
         patch("translator.asyncio.sleep", new=AsyncMock()):
        result = await t._post_with_retry("http://litellm:4000/v1/chat/completions", {}, b"{}", retries=1)

    assert result.status_code == 200
    assert call_count == 2


@pytest.mark.asyncio
async def test_post_with_retry_stops_after_retries_exhausted():
    err_resp = MagicMock()
    err_resp.status_code = 503

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=err_resp)

    with patch.object(t, "_client", mock_client), \
         patch("translator.asyncio.sleep", new=AsyncMock()):
        result = await t._post_with_retry("http://litellm:4000/v1/chat/completions", {}, b"{}", retries=2)

    assert result.status_code == 503
    # 1 initial + 2 retries = 3 calls
    assert mock_client.post.call_count == 3


def test_responses_proxy_timeout_non_stream():
    from fastapi.testclient import TestClient
    import httpx
    client = TestClient(t.app)

    async def mock_post_with_retry(*args, **kwargs):
        raise httpx.TimeoutException("Simulated upstream timeout")

    with patch("translator._post_with_retry", mock_post_with_retry), \
         patch.dict(os.environ, {"LITELLM_MASTER_KEY": "test-key"}):
        response = client.post(
            "/v1/responses",
            json={"model": "gpt-5.4", "messages": [{"role": "user", "content": "hello"}]}
        )

    assert response.status_code == 504
    data = response.json()
    assert "error" in data
    assert data["error"]["type"] == "timeout_error"
    assert "Upstream request timed out" in data["error"]["message"]


def test_responses_proxy_timeout_stream():
    from fastapi.testclient import TestClient
    import httpx
    client = TestClient(t.app)

    mock_client = MagicMock()
    mock_client.send = AsyncMock(side_effect=httpx.TimeoutException("Simulated stream timeout"))

    with patch.object(t, "_client", mock_client), \
         patch.dict(os.environ, {"LITELLM_MASTER_KEY": "test-key"}):
        response = client.post(
            "/v1/responses",
            json={"model": "gpt-5.4", "stream": True, "messages": [{"role": "user", "content": "hello"}]}
        )

    assert response.status_code == 504
    data = response.json()
    assert "error" in data
    assert data["error"]["type"] == "timeout_error"
    assert "Upstream request timed out" in data["error"]["message"]


