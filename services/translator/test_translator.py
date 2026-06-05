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


# ===========================================================================
# Per-provider routing signals (issue #59)
# ===========================================================================

class TestProviderOf(unittest.TestCase):
    """_provider_of model → provider-family mapping."""

    def test_anthropic(self):
        assert t._provider_of("claude-sonnet-4-6") == "anthropic"

    def test_openai(self):
        assert t._provider_of("gpt-5-4") == "openai"
        assert t._provider_of("o3-mini") == "openai"

    def test_google(self):
        assert t._provider_of("gemini-3-flash") == "google"

    def test_xai(self):
        assert t._provider_of("grok-4") == "xai"

    def test_moonshot(self):
        assert t._provider_of("kimi-k2") == "moonshot"

    def test_prefix_is_stripped(self):
        assert t._provider_of("AI-Gateway:claude-opus-4-7") == "anthropic"

    def test_unknown(self):
        assert t._provider_of("totally-made-up") == "unknown"

    def test_empty(self):
        assert t._provider_of("") == "unknown"


class TestOutcomeForStatus(unittest.TestCase):
    """_outcome_for_status classification."""

    def test_success(self):
        assert t._outcome_for_status(200) == "success"

    def test_rate_limited(self):
        assert t._outcome_for_status(429) == "rate_limited"

    def test_server_error(self):
        assert t._outcome_for_status(503) == "server_error"

    def test_client_error(self):
        assert t._outcome_for_status(400) == "client_error"
        # 429 is classified as rate_limited, not generic client_error
        assert t._outcome_for_status(429) != "client_error"


class TestModelFromContent(unittest.TestCase):
    """_model_from_content best-effort extraction."""

    def test_extracts_model(self):
        assert t._model_from_content(b'{"model": "gpt-5-4"}') == "gpt-5-4"

    def test_missing_model(self):
        assert t._model_from_content(b'{"messages": []}') == "-"

    def test_invalid_json(self):
        assert t._model_from_content(b"not json") == "-"


def _counter_value(counter, **labels):
    """Read a prometheus Counter/Histogram child's running total for given labels."""
    child = counter.labels(**labels)
    # Counter exposes ._value.get(); Histogram count is ._count.get()
    if hasattr(child, "_value"):
        return child._value.get()
    return child._count.get()


@pytest.mark.asyncio
async def test_post_with_retry_records_provider_signals():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    before = _counter_value(t.PROVIDER_REQUESTS, provider="openai", model="gpt-5-4", outcome="success")
    with patch.object(t, "_client", mock_client):
        await t._post_with_retry("http://litellm:4000/v1/chat/completions", {}, b'{"model": "gpt-5-4"}')
    after = _counter_value(t.PROVIDER_REQUESTS, provider="openai", model="gpt-5-4", outcome="success")
    assert after == before + 1


@pytest.mark.asyncio
async def test_post_with_retry_records_rate_limit_signal():
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)

    rl_before = _counter_value(t.PROVIDER_RATE_LIMITS, provider="anthropic", model="claude-sonnet-4-6")
    req_before = _counter_value(t.PROVIDER_REQUESTS, provider="anthropic", model="claude-sonnet-4-6", outcome="rate_limited")
    with patch.object(t, "_client", mock_client):
        # 429 is not retried by _post_with_retry, so exactly one signal is emitted
        await t._post_with_retry("http://litellm:4000/v1/chat/completions", {}, b'{"model": "claude-sonnet-4-6"}')
    rl_after = _counter_value(t.PROVIDER_RATE_LIMITS, provider="anthropic", model="claude-sonnet-4-6")
    req_after = _counter_value(t.PROVIDER_REQUESTS, provider="anthropic", model="claude-sonnet-4-6", outcome="rate_limited")
    assert rl_after == rl_before + 1
    assert req_after == req_before + 1


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




# ===========================================================================
# Admin status aggregator (issue #69)
# ===========================================================================

class TestAdminRedact(unittest.TestCase):
    def test_redacts_bearer(self):
        out, red = t._admin_redact("Authorization: Bearer abcdef1234567890abcd")
        assert "[redacted]" in out
        assert red is True

    def test_redacts_sk_key(self):
        out, red = t._admin_redact("key sk-abcdef1234567890abcd here")
        assert "sk-abcdef1234567890abcd" not in out
        assert red is True

    def test_plain_text_untouched(self):
        out, red = t._admin_redact("translator /metrics timed out")
        assert out == "translator /metrics timed out"
        assert red is False

    def test_truncates_long(self):
        out, _ = t._admin_redact("x" * (t.ADMIN_ERROR_MAXLEN + 50))
        assert len(out) <= t.ADMIN_ERROR_MAXLEN + 1


class TestAdminError(unittest.TestCase):
    def test_shape_and_redaction(self):
        e = t._admin_error("code1", "token=abcdefgh12345678", "src")
        assert e["code"] == "code1"
        assert e["source"] == "src"
        assert e["redacted"] is True
        assert "[redacted]" in e["message"]


class TestAdminParseProviderMetrics(unittest.TestCase):
    def test_parses_requests_and_rate_limits(self):
        text = (
            'translator_provider_requests_total{model="gpt-5-4",outcome="success",provider="openai"} 3.0\n'
            'translator_provider_rate_limits_total{model="claude-sonnet-4-6",provider="anthropic"} 1.0\n'
            'some_other_metric{x="y"} 9\n'
        )
        signals = t._admin_parse_provider_metrics(text)
        kinds = {s["kind"] for s in signals}
        assert "requests" in kinds
        assert "rate_limited" in kinds
        req = next(s for s in signals if s["kind"] == "requests")
        assert req["provider"] == "openai"
        assert req["model"] == "gpt-5-4"
        assert req["outcome"] == "success"
        assert req["value"] == 3.0

    def test_empty(self):
        assert t._admin_parse_provider_metrics("") == []


class TestAdminModelsPanel(unittest.TestCase):
    def _config(self):
        return {"model_list": [
            {"model_name": "claude-sonnet-4-6"},
            {"model_name": "gpt-5-4"},
        ]}

    def test_ok_when_all_visible(self):
        panel = t._admin_models_panel(self._config(), ["claude-sonnet-4-6", "gpt-5-4"], [])
        assert panel["status"] == "ok"
        assert panel["data"]["configured_count"] == 2
        assert panel["data"]["drift"] == []

    def test_drift_when_configured_not_visible(self):
        panel = t._admin_models_panel(self._config(), ["claude-sonnet-4-6"], [])
        assert panel["status"] == "warning"
        assert any(d["model"] == "gpt-5-4" for d in panel["data"]["drift"])

    def test_drift_when_visible_not_configured(self):
        panel = t._admin_models_panel(self._config(), ["claude-sonnet-4-6", "gemini-3-flash"], [])
        assert panel["status"] == "warning"
        assert any(
            d["model"] == "gemini-3-flash" and d["kind"] == "visible_not_configured"
            for d in panel["data"]["drift"]
        )

    def test_warning_when_visible_unknown(self):
        panel = t._admin_models_panel(self._config(), None, [])
        assert panel["status"] == "warning"


class TestAdminRoutingPanel(unittest.TestCase):
    def test_extracts_router_settings_and_fallbacks(self):
        config = {
            "router_settings": {"routing_strategy": "latency-based-routing", "cooldown_time": 60},
            "litellm_settings": {"fallbacks": [{"gpt-5-4": ["claude-sonnet-4-6"]}]},
        }
        metrics = (
            'translator_provider_requests_total{model="gpt-5-4",outcome="success",provider="openai"} 2.0\n'
            'translator_provider_rate_limits_total{model="claude-sonnet-4-6",provider="anthropic"} 1.0\n'
        )
        panel = t._admin_routing_panel(config, metrics, [])
        assert panel["status"] == "ok"
        assert panel["data"]["router_settings"]["cooldown_time"] == 60
        assert panel["data"]["fallbacks"][0]["model"] == "gpt-5-4"
        assert panel["data"]["provider_signals"]
        assert len(panel["data"]["provider_signals"]) == 2
        sig1 = next(s for s in panel["data"]["provider_signals"] if s["provider"] == "openai")
        assert sig1["model"] == "gpt-5-4"
        assert sig1["outcome"] == "success"
        assert sig1["requests"] == 2
        sig2 = next(s for s in panel["data"]["provider_signals"] if s["provider"] == "anthropic")
        assert sig2["model"] == "claude-sonnet-4-6"
        assert sig2["outcome"] == "rate_limited"
        assert sig2["requests"] == 1
        assert panel["data"]["cooldown_events"] == []

    def test_warning_when_metrics_missing(self):
        panel = t._admin_routing_panel({}, None, [])
        assert panel["status"] == "warning"


class TestAdminConfigDriftPanel(unittest.TestCase):
    def test_error_when_config_none(self):
        panel = t._admin_config_drift_panel(None, [t._admin_error("x", "y", "z")])
        assert panel["status"] == "error"
        assert any(c["name"] == "litellm_yaml_parse" and c["status"] == "error" for c in panel["data"]["checks"])


class TestAdminRunReadonlyCommand(unittest.TestCase):
    def test_missing_command(self):
        out, errors = t._admin_run_readonly_command(["/nonexistent/cmd-xyz", "health"], timeout=1.0)
        assert out == ""
        assert errors and errors[0]["code"] == "command_not_found"


@pytest.mark.asyncio
async def test_admin_status_endpoint_shape():
    from fastapi.testclient import TestClient

    async def fake_visible():
        return ["claude-sonnet-4-6"], []

    async def fake_metrics():
        return 'translator_provider_requests_total{model="claude-sonnet-4-6",outcome="success",provider="anthropic"} 1.0\n', []

    with patch.object(t, "_admin_load_litellm_config", return_value=({"model_list": [{"model_name": "claude-sonnet-4-6"}]}, [])), \
         patch.object(t, "_admin_fetch_visible_models", fake_visible), \
         patch.object(t, "_admin_fetch_metrics_text", fake_metrics), \
         patch.object(t, "_admin_run_readonly_command", lambda *a, **k: ("", [])):
        client = TestClient(t.app)
        resp = client.get("/admin/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == "admin-console.v1"
    assert set(body["panels"].keys()) == {"health", "models", "providers", "routing", "config_drift", "token_analytics"}
    assert body["panels"]["health"]["status"] == "ok"
    # No obvious secret leakage in the serialized response.
    raw = json.dumps(body)
    assert "Bearer " not in raw


@pytest.mark.asyncio
async def test_admin_dashboard_page():
    from fastapi.testclient import TestClient

    client = TestClient(t.app)
    resp = client.get("/admin/dashboard")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    # Page is self-contained and fetches the status endpoint client-side.
    assert "/admin/status" in html
    assert "AI Gateway" in html
    # The server-rendered HTML must not embed secrets.
    assert "Bearer " not in html
    assert "sk-" not in html


import httpx  # noqa: E402  (used by the catch-all timeout tests below)


class _TimeoutClient:
    async def request(self, *args, **kwargs):
        raise httpx.TimeoutException("timeout")


class _ConnectionErrorClient:
    async def request(self, *args, **kwargs):
        raise httpx.ConnectError("connect failed")


class _StreamTimeoutContext:
    async def __aenter__(self):
        raise httpx.TimeoutException("timeout")

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _StreamTimeoutClient:
    def stream(self, *args, **kwargs):
        return _StreamTimeoutContext()


def test_proxy_non_stream_timeout_returns_structured_504():
    from fastapi.testclient import TestClient

    client = TestClient(t.app)
    with patch.object(t, "_client", _TimeoutClient()):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hello"}]},
        )
    assert resp.status_code == 504
    data = resp.json()
    assert data["error"]["type"] == "timeout_error"
    assert "Upstream request timed out" in data["error"]["message"]


def test_proxy_non_stream_connection_failure_returns_structured_502():
    from fastapi.testclient import TestClient

    client = TestClient(t.app)
    with patch.object(t, "_client", _ConnectionErrorClient()):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "hello"}]},
        )
    assert resp.status_code == 502
    data = resp.json()
    assert data["error"]["type"] == "connection_error"


def test_proxy_stream_timeout_yields_error_event():
    from fastapi.testclient import TestClient

    client = TestClient(t.app)
    with patch.object(t, "_client", _StreamTimeoutClient()):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "claude-sonnet-4-6", "stream": True, "messages": [{"role": "user", "content": "hello"}]},
        )
    assert resp.status_code == 200
    assert "timeout_error" in resp.text
    assert "Upstream request timed out" in resp.text
