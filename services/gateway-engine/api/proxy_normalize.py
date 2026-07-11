"""Content / messages / tools / model resolve / body patch helpers."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from api.proxy_common import _deps, log

# ── Shared content normalisation (Responses API / Cursor) ────────────────────


def _normalize_content_item(c: dict) -> dict | None:
    ct = c.get("type", "")
    if ct in ("input_text", "output_text", "text", "refusal"):
        return {"type": "text", "text": c.get("text", c.get("refusal", ""))}
    if ct == "input_image":
        detail = c.get("detail", "auto")
        if "image_url" in c:
            img = c["image_url"]
            if isinstance(img, str):
                img = {"url": img, "detail": detail}
            return {"type": "image_url", "image_url": img}
        if "url" in c:
            return {
                "type": "image_url",
                "image_url": {"url": c["url"], "detail": detail},
            }
        if "source" in c:
            src = c["source"]
            if src.get("type") == "url":
                return {
                    "type": "image_url",
                    "image_url": {"url": src["url"], "detail": detail},
                }
            if src.get("type") == "base64":
                media = src.get("media_type", "image/jpeg")
                return {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media};base64,{src['data']}",
                        "detail": detail,
                    },
                }
        return None
    if ct == "input_file":
        text = c.get("text") or c.get("filename") or "[file]"
        return {"type": "text", "text": text}
    return c


def _normalize_content(content):
    if isinstance(content, str) or content is None:
        return content
    if not isinstance(content, list):
        return str(content)
    normalized = []
    for item in content:
        if isinstance(item, str):
            normalized.append({"type": "text", "text": item})
        elif isinstance(item, dict):
            conv = _normalize_content_item(item)
            if conv is not None:
                normalized.append(conv)
    if all(c.get("type") == "text" for c in normalized):
        return "".join(c.get("text", "") for c in normalized)
    return normalized


def _responses_input_to_messages(inp) -> list:
    if isinstance(inp, str):
        return [{"role": "user", "content": inp}]
    if not isinstance(inp, list):
        return []

    messages = []
    pending_calls: list[dict] = []

    def flush_calls():
        if pending_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": list(pending_calls),
                }
            )
            pending_calls.clear()

    for item in inp:
        if not isinstance(item, dict):
            continue
        t = item.get("type", "")

        if t == "message" or (not t and "role" in item):
            flush_calls()
            role = item.get("role", "user")
            content = item.get("content", "")
            if isinstance(content, list):
                tool_blocks = [
                    c for c in content if isinstance(c, dict) and c.get("type") in ("tool_use", "function_call")
                ]
                if tool_blocks:
                    tool_calls = []
                    text_parts = []
                    for c in content:
                        if not isinstance(c, dict):
                            continue
                        if c.get("type") in ("tool_use", "function_call"):
                            args = c.get("input", c.get("arguments", {}))
                            tool_calls.append(
                                {
                                    "id": c.get("id", c.get("call_id", "")),
                                    "type": "function",
                                    "function": {
                                        "name": c.get("name", ""),
                                        "arguments": json.dumps(args) if isinstance(args, dict) else str(args),
                                    },
                                }
                            )
                        elif c.get("type") in ("text", "input_text", "output_text"):
                            text_parts.append(c.get("text", ""))
                    messages.append(
                        {
                            "role": "assistant",
                            "content": "".join(text_parts) or None,
                            "tool_calls": tool_calls,
                        }
                    )
                    continue
            messages.append({"role": role, "content": _normalize_content(content)})

        elif t == "function_call":
            args = item.get("arguments", "{}")
            pending_calls.append(
                {
                    "id": item.get("id", item.get("call_id", "")),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": args if isinstance(args, str) else json.dumps(args),
                    },
                }
            )

        elif t == "function_call_output":
            flush_calls()
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": item.get("call_id", item.get("id", "")),
                    "content": str(item.get("output", "")),
                }
            )

    flush_calls()
    return messages


def _normalize_messages(messages: list) -> tuple[list, bool]:
    changed = False
    out = []
    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        content = msg.get("content")
        normed = _normalize_content(content)
        if normed != content:
            changed = True
            msg = {**msg, "content": normed}
        out.append(msg)
    return out, changed


def _normalize_tools(tools: list) -> tuple[list, bool]:
    changed = False
    out = []
    for tool in tools:
        if not isinstance(tool, dict):
            out.append(tool)
            continue
        if tool.get("type") == "function" and "function" not in tool and "name" in tool:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {}),
                    },
                }
            )
            changed = True
        else:
            out.append(tool)
    return out, changed


def _normalize_model(name: str) -> str:
    return name.replace(".", "-")


@dataclass
class _ResolvedModel:
    requested_model: str
    effective_model: str
    change_reason: str
    severity: str
    tool_capability_assumption: str


def _emit_model_resolution(res: _ResolvedModel, endpoint: str, wants_tools: bool) -> None:
    if res.requested_model == res.effective_model and res.severity == "info":
        return
    level = logging.WARNING if res.severity == "warn" else logging.INFO
    log.log(
        level,
        "model_resolution endpoint=%s requested=%s effective=%s reason=%s severity=%s tools=%s assumption=%s",
        endpoint,
        res.requested_model,
        res.effective_model,
        res.change_reason,
        res.severity,
        wants_tools,
        res.tool_capability_assumption,
    )


_PREVIEW_SUFFIX_RE = re.compile(r"-(preview|exp)(-[0-9]{2}-[0-9]{2})?$")


def _maybe_preview_fallback(model: str, wants_tools: bool) -> tuple[str, str, str, str]:
    if not wants_tools:
        return model, "unknown_passthrough", "warn", "native"
    base = _PREVIEW_SUFFIX_RE.sub("", model)
    if base != model:
        return base, "preview_suffix_fallback", "warn", "fallback"
    return model, "unknown_preview_passthrough", "warn", "assumed"


def _resolve_model(
    model: str, endpoint: str, wants_tools: bool = False, gemini_map: dict | None = None
) -> _ResolvedModel:
    requested = model or ""
    effective = requested
    reason = "passthrough"
    severity = "info"
    assumption = "native"

    if effective.startswith(_deps().model_prefix):
        effective = effective[len(_deps().model_prefix) :]
        reason = "prefix_strip"

    if endpoint == "gemini":
        base = effective.removesuffix("-customtools")
        if base != effective:
            effective = base
            reason = "customtools_suffix_strip"

        gmap = gemini_map or {}
        mapped = gmap.get(effective)
        if mapped:
            if mapped != effective:
                reason = "gemini_map"
            effective = mapped
        elif "preview" in effective or "exp" in effective:
            effective, reason, severity, assumption = _maybe_preview_fallback(effective, wants_tools)
    else:
        if "." in effective:
            effective = _normalize_model(effective)
            reason = "dotted_to_dashed"
        if ("preview" in effective or "exp" in effective) and endpoint in (
            "responses",
            "chat",
            "claude",
        ):
            # Warn for drift even when unchanged for non-Gemini paths.
            severity = "warn"
            reason = "preview_passthrough"

    res = _ResolvedModel(requested, effective, reason, severity, assumption)
    _emit_model_resolution(res, endpoint, wants_tools)
    return res


def _strip_prefix(body: bytes) -> tuple[bytes, bool]:
    try:
        data = json.loads(body)
    except Exception:
        return body, False
    model = data.get("model", "")
    if isinstance(model, str) and model.startswith(_deps().model_prefix):
        data["model"] = model[len(_deps().model_prefix) :]
        return json.dumps(data).encode(), True
    return body, False


def _add_prefix_to_models_response(body: bytes) -> bytes:
    try:
        data = json.loads(body)
    except Exception:
        return body
    if not isinstance(data.get("data"), list):
        return body
    for entry in data["data"]:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            if not entry["id"].startswith(_deps().model_prefix):
                entry["id"] = _deps().model_prefix + entry["id"]
    return json.dumps(data).encode()


def _patch_body(path: str, body: bytes) -> tuple[bytes, bool]:
    if path.rstrip("/") not in ("v1/chat/completions", "chat/completions"):
        return body, False
    try:
        data = json.loads(body)
    except Exception:
        return body, False

    changed = False

    if "messages" not in data and "input" in data:
        inp = data.pop("input")
        if isinstance(inp, list):
            log.info(
                "Input item types: %s",
                [i.get("type") if isinstance(i, dict) else type(i).__name__ for i in inp],
            )
        data["messages"] = _responses_input_to_messages(inp)
        n = len(inp) if isinstance(inp, list) else 1
        log.info(
            "Translated Responses API input (%d items) → %d messages",
            n,
            len(data["messages"]),
        )
        changed = True
    elif "messages" in data:
        data["messages"], msg_changed = _normalize_messages(data["messages"])
        if msg_changed:
            log.info("Normalised content types in %d messages", len(data["messages"]))
            changed = True

    if "tools" in data:
        data["tools"], tools_changed = _normalize_tools(data["tools"])
        if tools_changed:
            log.info("Normalised %d tools to Chat Completions format", len(data["tools"]))
            changed = True

    raw_model = data.get("model", "")
    if isinstance(raw_model, str):
        resolved = _resolve_model(raw_model, endpoint="chat", wants_tools=bool(data.get("tools")))
        if resolved.effective_model != raw_model:
            data["model"] = resolved.effective_model
            changed = True

    if changed:
        return json.dumps(data).encode(), True
    return body, False
