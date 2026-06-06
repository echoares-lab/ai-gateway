"""Gemini CLI format ↔ OpenAI Chat Completions converters."""

import hashlib
import json
import logging
import os

import httpx
from providers.base import ResolveModelFn

log = logging.getLogger("translator")

# Legacy Google model names that need redirecting to current equivalents.
# Managed by hand — these don't change once a generation is deprecated.
_GEMINI_LEGACY_MAP = {
    "gemini-pro": "gemini-3-1-pro-preview",
    "gemini-1.0-pro": "gemini-3-1-pro-preview",
    "gemini-1.5-pro": "gemini-3-1-pro-preview",
    "gemini-1.5-pro-latest": "gemini-3-1-pro-preview",
    "gemini-1.5-flash": "gemini-3-flash-preview",
    "gemini-1.5-flash-latest": "gemini-3-flash-preview",
    "gemini-2.0-flash": "gemini-3-flash-preview",
    "gemini-2.0-flash-exp": "gemini-3-flash-preview",
}

# Current dotted→dashed mappings are kept in gemini-model-map.json and managed
# by sync-models. This module watches the file and reloads on change.
_GEMINI_MAP_PATH = "/app/gemini-model-map.json"
_gemini_map_mtime: float = 0.0
_gemini_map_dynamic: dict = {}


def get_gemini_map() -> dict:
    global _gemini_map_mtime, _gemini_map_dynamic
    try:
        mtime = os.stat(_GEMINI_MAP_PATH).st_mtime
        if mtime != _gemini_map_mtime:
            with open(_GEMINI_MAP_PATH) as f:
                _gemini_map_dynamic = json.load(f)
            _gemini_map_mtime = mtime
            log.info("Reloaded gemini-model-map.json (%d entries)", len(_gemini_map_dynamic))
    except Exception:
        pass
    return {**_GEMINI_LEGACY_MAP, **_gemini_map_dynamic}


FINISH_MAP = {
    "stop": "STOP",
    "length": "MAX_TOKENS",
    "tool_calls": "STOP",
    "content_filter": "SAFETY",
}


def _find_tool_call_id_in_history(history: list, target_name: str, current_index: int) -> str:
    """Scan backward from current_index in conversation history to find the most recent
    matching tool call by name and return a deterministic, valid alphanumeric ID.
    Supports both Gemini 'contents' format and standard OpenAI 'messages' format."""
    for i in range(current_index - 1, -1, -1):
        msg = history[i]
        if not isinstance(msg, dict):
            continue

        # 1. Check standard OpenAI format (messages)
        tool_calls = msg.get("tool_calls", [])
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    fn = tc.get("function", {})
                    if isinstance(fn, dict) and fn.get("name") == target_name:
                        tc_id = tc.get("id")
                        if tc_id:
                            return tc_id
                        h = hashlib.md5(f"{target_name}_{i}".encode()).hexdigest()[:20]
                        return f"call_{h}"

        # 2. Check Gemini format (contents)
        parts = msg.get("parts", [])
        if isinstance(parts, list):
            for p in parts:
                if isinstance(p, dict) and "functionCall" in p:
                    fc = p["functionCall"]
                    if isinstance(fc, dict) and fc.get("name") == target_name:
                        h = hashlib.md5(f"{target_name}_{i}".encode()).hexdigest()[:20]
                        return f"call_{h}"

    # Fallback if not found in history
    h = hashlib.md5(f"{target_name}_fallback".encode()).hexdigest()[:20]
    return f"call_{h}"


def req_to_oai(model: str, body: dict, *, resolve_model: ResolveModelFn, gemini_map: dict | None = None) -> dict:
    messages = []

    sys_inst = body.get("systemInstruction", {})
    if isinstance(sys_inst, dict):
        sys_text = "".join(p.get("text", "") for p in sys_inst.get("parts", []))
        if sys_text:
            messages.append({"role": "system", "content": sys_text})

    contents = body.get("contents", [])
    for content_idx, content in enumerate(contents):
        role = "assistant" if content.get("role") == "model" else content.get("role", "user")
        parts = content.get("parts", [])

        func_calls = [p["functionCall"] for p in parts if "functionCall" in p]
        func_resps = [p["functionResponse"] for p in parts if "functionResponse" in p]
        texts = [p.get("text", "") for p in parts if "text" in p]
        inline = [p for p in parts if "inlineData" in p or "fileData" in p]

        if func_resps:
            for fr in func_resps:
                tc_id = _find_tool_call_id_in_history(contents, fr["name"], content_idx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps(fr.get("response", {})),
                    }
                )
        elif func_calls:
            tool_calls = []
            for fc in func_calls:
                h = hashlib.md5(f"{fc['name']}_{content_idx}".encode()).hexdigest()[:20]
                tc_id = f"call_{h}"
                tool_calls.append(
                    {
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": json.dumps(fc.get("args", {})),
                        },
                    }
                )
            messages.append(
                {
                    "role": "assistant",
                    "content": "".join(texts) or None,
                    "tool_calls": tool_calls,
                }
            )
        elif inline:
            content_list = []
            for p in parts:
                if "text" in p:
                    content_list.append({"type": "text", "text": p["text"]})
                elif "inlineData" in p:
                    d = p["inlineData"]
                    content_list.append(
                        {"type": "image_url", "image_url": {"url": f"data:{d['mimeType']};base64,{d['data']}"}}
                    )
            messages.append({"role": role, "content": content_list})
        else:
            messages.append({"role": role, "content": "".join(texts)})

    # Google exposes variants like gemini-3.1-pro-preview-customtools for tool-aware routing;
    # our CLIProxy backend handles tools with the base model so we strip known suffixes.
    gmap = gemini_map if gemini_map is not None else get_gemini_map()
    resolved = resolve_model(model, endpoint="gemini", wants_tools=bool(body.get("tools")), gemini_map=gmap)
    oai = {"model": resolved.effective_model, "messages": messages}

    gc = body.get("generationConfig", {})
    if "maxOutputTokens" in gc:
        oai["max_tokens"] = gc["maxOutputTokens"]
    if "temperature" in gc:
        oai["temperature"] = gc["temperature"]
    if "topP" in gc:
        oai["top_p"] = gc["topP"]
    if "stopSequences" in gc:
        oai["stop"] = gc["stopSequences"]

    tools_out = []
    for tool_obj in body.get("tools", []):
        for fd in tool_obj.get("functionDeclarations", []):
            tools_out.append(
                {
                    "type": "function",
                    "function": {
                        "name": fd["name"],
                        "description": fd.get("description", ""),
                        "parameters": fd.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
            )
    if tools_out:
        oai["tools"] = tools_out

    mode = body.get("toolConfig", {}).get("functionCallingConfig", {}).get("mode", "")
    if mode == "ANY":
        oai["tool_choice"] = "required"
    elif mode == "NONE":
        oai["tool_choice"] = "none"

    return oai


def oai_to_resp(oai: dict, model: str) -> dict:
    choice = oai.get("choices", [{}])[0]
    msg = choice.get("message", {})
    finish = choice.get("finish_reason", "stop")

    parts = []
    if msg.get("content"):
        parts.append({"text": msg["content"]})
    for tc in msg.get("tool_calls", []):
        fn = tc["function"]
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except Exception:
            args = {}
        parts.append({"functionCall": {"name": fn["name"], "args": args}})

    usage = oai.get("usage", {})
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts},
                "finishReason": FINISH_MAP.get(finish, "STOP"),
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": usage.get("prompt_tokens", 0),
            "candidatesTokenCount": usage.get("completion_tokens", 0),
            "totalTokenCount": usage.get("total_tokens", 0),
        },
        "modelVersion": model,
    }


async def stream(oai_lines):
    """Convert OpenAI SSE lines to Gemini SSE chunks."""
    tool_buffers: dict[int, dict] = {}

    try:
        async for line in oai_lines:
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except Exception:
                continue

            choice = chunk.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            finish = choice.get("finish_reason")

            parts = []
            if delta.get("content"):
                parts.append({"text": delta["content"]})

            for tc in delta.get("tool_calls", []):
                idx = tc.get("index", 0)
                fn = tc.get("function", {})
                if idx not in tool_buffers:
                    tool_buffers[idx] = {"name": fn.get("name", ""), "args": ""}
                if fn.get("name"):
                    tool_buffers[idx]["name"] = fn["name"]
                if fn.get("arguments"):
                    tool_buffers[idx]["args"] += fn["arguments"]

            # Flush completed tool calls on the finish chunk
            if finish:
                for tb in tool_buffers.values():
                    if tb["name"]:
                        try:
                            args = json.loads(tb["args"] or "{}")
                        except Exception:
                            args = {}
                        parts.append({"functionCall": {"name": tb["name"], "args": args}})

            if parts or finish:
                gemini_chunk = {
                    "candidates": [
                        {
                            "content": {"role": "model", "parts": parts},
                            "finishReason": FINISH_MAP.get(finish, "") if finish else None,
                            "index": 0,
                        }
                    ]
                }
                yield f"data: {json.dumps(gemini_chunk)}\n\n"
    except httpx.HTTPError as exc:
        log.error("Gemini stream connection error: %s", exc)
