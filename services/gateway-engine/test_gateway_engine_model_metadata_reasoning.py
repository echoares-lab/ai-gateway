"""Unit tests for model metadata capability expansion and reasoning normalization (Epic #486)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from core.model_registry import (
    ModelRegistryPatchRequest,
    ModelRegistryRecord,
    ModelRegistryWriteRequest,
)
from providers.claude import msg_to_oai, oai_to_resp, req_to_oai


def test_model_registry_record_supports_reasoning_and_context_window() -> None:
    rec = ModelRegistryRecord(
        model_id="test-model",
        upstream_model="test-model",
        litellm_model="openai/test-model",
        supports_reasoning=True,
        context_window=128000,
    )
    assert rec.supports_reasoning is True
    assert rec.context_window == 128000


def test_model_registry_write_request_to_record() -> None:
    req = ModelRegistryWriteRequest(
        model_id="claude-sonnet-4-6",
        upstream_model="claude-sonnet-4-6",
        supports_reasoning=True,
        context_window=200000,
    )
    rec = req.to_record()
    assert rec.supports_reasoning is True
    assert rec.context_window == 200000


def test_model_registry_patch_request_apply() -> None:
    rec = ModelRegistryRecord(
        model_id="claude-haiku-4-5",
        upstream_model="claude-haiku-4-5",
        litellm_model="anthropic/claude-haiku-4-5",
        supports_reasoning=False,
        context_window=200000,
    )
    patch = ModelRegistryPatchRequest(supports_reasoning=True)
    updated = patch.apply(rec)
    assert updated.supports_reasoning is True
    assert updated.context_window == 200000


def test_model_registry_yaml_config_has_reasoning_and_context_window() -> None:
    file_path = Path(__file__).resolve()
    candidates = [
        file_path.parent.parent / "config" / "model-registry.yaml",
        file_path.parent / "config" / "model-registry.yaml",
        Path("config/model-registry.yaml"),
        Path("../config/model-registry.yaml"),
    ]
    config_path = None
    for cand in candidates:
        if cand.is_file():
            config_path = cand
            break

    if config_path is None:
        pytest.skip("config/model-registry.yaml not found")

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    models = {m["model_id"]: m for m in data.get("models", [])}

    assert models["claude-sonnet-4-6"]["supports_reasoning"] is True
    assert models["claude-sonnet-4-6"]["context_window"] == 200000
    assert models["gemini-3-flash"]["supports_reasoning"] is True
    assert models["gemini-3-flash"]["context_window"] == 1000000
    assert models["gpt-5-4"]["supports_reasoning"] is True
    assert models["gpt-5-4"]["context_window"] == 128000


def test_claude_msg_to_oai_maps_thinking_blocks() -> None:
    msg = {
        "role": "assistant",
        "content": [
            {"type": "thinking", "thinking": "Planning answer step 1"},
            {"type": "text", "text": "Here is the answer."},
        ],
    }
    oai = msg_to_oai(msg)
    assert len(oai) == 1
    assert oai[0]["role"] == "assistant"
    assert oai[0]["content"] == "Here is the answer."
    assert oai[0]["reasoning_content"] == "Planning answer step 1"


def test_claude_oai_to_resp_maps_reasoning_content() -> None:
    oai = {
        "id": "123",
        "model": "claude-sonnet-4-6",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Final response",
                    "reasoning_content": "Internal thought process",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }
    resp = oai_to_resp(oai)
    assert resp["role"] == "assistant"
    assert len(resp["content"]) == 2
    assert resp["content"][0]["type"] == "thinking"
    assert resp["content"][0]["thinking"] == "Internal thought process"
    assert resp["content"][1]["type"] == "text"
    assert resp["content"][1]["text"] == "Final response"


def test_claude_req_to_oai_translates_thinking_budget() -> None:
    body = {
        "model": "claude-sonnet-4-6",
        "messages": [{"role": "user", "content": "Hello"}],
        "thinking": {"type": "enabled", "budget_tokens": 8192},
    }
    oai = req_to_oai(
        body, resolve_model=lambda m, endpoint, wants_tools: type("Resolved", (), {"effective_model": m})()
    )
    assert oai["reasoning_effort"] == "high"
