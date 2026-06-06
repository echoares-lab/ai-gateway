"""Anthropic Messages API ↔ OpenAI Chat Completions converters."""

import json
import logging
import uuid

import httpx
from providers.base import ResolveModelFn

log = logging.getLogger("translator")


def msg_to_oai(msg: dict) -> list[dict]:
    role = msg.get("role", "user")
    content = msg.get("content", "")

    if isinstance(content, str):
        return [{"role": role, "content": content}]
    if not isinstance(content, list):
        return [{"role": role, "content": str(content)}]

    tool_uses = [c for c in content if c.get("type") == "tool_use"]
    tool_results = [c for c in content if c.get("type") == "tool_result"]
    text_blocks = [c for c in content if c.get("type") == "text"]
    image_blocks = [c for c in content if c.get("type") == "image"]

    if tool_results:
        out = []
        for tr in tool_results:
            tr_content = tr.get("content", "")
            if isinstance(tr_content, list):
                tr_content = " ".join(b.get("text", "") for b in tr_content if b.get("type") == "text")
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": tr.get("tool_use_id", ""),
                    "content": str(tr_content),
                }
            )
        return out

    if tool_uses:
        text = "".join(b.get("text", "") for b in text_blocks)
        tool_calls = []
        for tu in tool_uses:
            inp = tu.get("input", {})
            tool_calls.append(
                {
                    "id": tu.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tu.get("name", ""),
                        "arguments": json.dumps(inp) if isinstance(inp, dict) else str(inp),
                    },
                }
            )
        return [{"role": "assistant", "content": text or None, "tool_calls": tool_calls}]

    if image_blocks:
        content_list = []
        for block in content:
            if block.get("type") == "text":
                content_list.append({"type": "text", "text": block.get("text", "")})
            elif block.get("type") == "image":
                src = block.get("source", {})
                if src.get("type") == "base64":
                    url = f"data:{src.get('media_type', 'image/jpeg')};base64,{src.get('data', '')}"
                    content_list.append({"type": "image_url", "image_url": {"url": url}})
                elif src.get("type") == "url":
                    content_list.append({"type": "image_url", "image_url": {"url": src.get("url", "")}})
        return [{"role": role, "content": content_list}]

    return [{"role": role, "content": "".join(b.get("text", "") for b in text_blocks)}]


def req_to_oai(body: dict, *, resolve_model: ResolveModelFn) -> dict:
    resolved = resolve_model(body.get("model", ""), endpoint="claude", wants_tools=bool(body.get("tools")))
    model = resolved.effective_model
    if "[" in model and model.endswith("]"):
        model = model.split("[")[0]

    messages = []

    system = body.get("system", "")
    if isinstance(system, list):
        system = "".join(b.get("text", "") for b in system if b.get("type") == "text")
    if system:
        messages.append({"role": "system", "content": system})

    for msg in body.get("messages", []):
        messages.extend(msg_to_oai(msg))

    oai: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": body.get("max_tokens", 4096),
    }

    if "temperature" in body:
        oai["temperature"] = body["temperature"]
    if "top_p" in body:
        oai["top_p"] = body["top_p"]
    if "stop_sequences" in body:
        oai["stop"] = body["stop_sequences"]

    tools = body.get("tools", [])
    if tools:
        oai["tools"] = []
        for t in tools:
            oai["tools"].append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                    },
                }
            )

    tc = body.get("tool_choice", {})
    if isinstance(tc, dict) and tc:
        tc_type = tc.get("type", "")
        if tc_type == "auto":
            oai["tool_choice"] = "auto"
        elif tc_type == "any":
            oai["tool_choice"] = "required"
        elif tc_type == "tool":
            oai["tool_choice"] = {"type": "function", "function": {"name": tc.get("name", "")}}

    return oai


def oai_to_resp(oai: dict) -> dict:
    choice = oai.get("choices", [{}])[0]
    msg = choice.get("message", {})
    finish = choice.get("finish_reason", "stop")
    usage = oai.get("usage", {})

    content = []
    if msg.get("content"):
        content.append({"type": "text", "text": msg["content"]})

    stop_reason = "end_turn"
    for tc in msg.get("tool_calls", []):
        fn = tc["function"]
        stop_reason = "tool_use"
        try:
            inp = json.loads(fn.get("arguments", "{}"))
        except Exception:
            inp = {}
        content.append(
            {
                "type": "tool_use",
                "id": tc.get("id", ""),
                "name": fn.get("name", ""),
                "input": inp,
            }
        )

    if finish == "length":
        stop_reason = "max_tokens"

    return {
        "id": f"msg_{oai.get('id', uuid.uuid4().hex)}",
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": oai.get("model", ""),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


async def stream(oai_lines, model: str):
    """Convert OpenAI SSE lines to Anthropic SSE events."""
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 1}}})}\n\n"
    yield f"event: ping\ndata: {json.dumps({'type': 'ping'})}\n\n"

    text_block_index: int | None = None
    text_buffer = ""
    tool_blocks: dict[int, dict] = {}  # oai index → {id, name, args, block_index}
    next_block = 0
    finish_reason = "end_turn"
    output_tokens = 0

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
            usage = chunk.get("usage", {})

            if usage.get("completion_tokens"):
                output_tokens = usage["completion_tokens"]
            if finish:
                if finish == "tool_calls":
                    finish_reason = "tool_use"
                elif finish == "length":
                    finish_reason = "max_tokens"

            text = delta.get("content", "")
            if text:
                if text_block_index is None:
                    text_block_index = next_block
                    next_block += 1
                    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': text_block_index, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                text_buffer += text
                yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': text_block_index, 'delta': {'type': 'text_delta', 'text': text}})}\n\n"

            for tc_delta in delta.get("tool_calls", []):
                idx = tc_delta.get("index", 0)
                fn = tc_delta.get("function", {})
                if idx not in tool_blocks:
                    tc_id = tc_delta.get("id", f"toolu_{uuid.uuid4().hex[:24]}")
                    tc_name = fn.get("name", "")
                    bi = next_block
                    next_block += 1
                    tool_blocks[idx] = {"id": tc_id, "name": tc_name, "args": "", "block_index": bi}
                    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': bi, 'content_block': {'type': 'tool_use', 'id': tc_id, 'name': tc_name, 'input': {}}})}\n\n"
                if fn.get("name") and not tool_blocks[idx]["name"]:
                    tool_blocks[idx]["name"] = fn["name"]
                if fn.get("arguments"):
                    tool_blocks[idx]["args"] += fn["arguments"]
                    bi = tool_blocks[idx]["block_index"]
                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': bi, 'delta': {'type': 'input_json_delta', 'partial_json': fn['arguments']}})}\n\n"
    except httpx.HTTPError as exc:
        log.error("Claude stream connection error: %s", exc)

    if text_block_index is not None:
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': text_block_index})}\n\n"

    for idx, tb in sorted(tool_blocks.items()):
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': tb['block_index']})}\n\n"

    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': finish_reason, 'stop_sequence': None}, 'usage': {'output_tokens': output_tokens}})}\n\n"
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"
