#!/usr/bin/env python3
"""Direct gateway protocol checks — no client CLI involved.

Tests the two gaps identified against 01 Projects/AI-Gateway/Specs/FEATURE_CANDIDATES.md C-RT-6:
  1. Reasoning-token usage accounting on /v1/chat/completions vs the Codex
     /v1/responses shape (proxy_responses.py hardcodes
     output_tokens_details.reasoning_tokens to 0 — this check confirms
     whether that's still true and whether the underlying chat-completions
     usage actually carries a real value that's being discarded).
  2. Streaming tool-call delta integrity on /v1/chat/completions: accumulate
     SSE tool-call argument deltas and confirm they parse as valid JSON
     matching the tool schema, per model — both a single call and two
     parallel calls in the same turn (the latter exercises index-keyed
     delta accumulation across concurrent calls, the risk flagged against
     providers/gemini.py's tool_buffers heuristic).

See 01 Projects/AI-Gateway/Specs/tool-use-eval.md and scripts/eval/README.md for context.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
            },
            "required": ["city", "unit"],
        },
    },
}

REASONING_PROMPT = (
    "Solve this step by step, showing your reasoning: a train leaves city A "
    "at 60mph, another leaves city B (300 miles away) at 40mph toward A at "
    "the same time. How many minutes until they meet? Reply with just the "
    "number of minutes as your final answer after reasoning."
)

TOOL_PROMPT = "What's the weather in Boston? Use fahrenheit. Call the tool, don't guess."

PARALLEL_TOOL_PROMPT = (
    "Call the get_weather tool twice in the same turn, once for Boston using "
    "fahrenheit and once for Miami using celsius. Make both tool calls, don't "
    "guess either answer, and don't ask a follow-up question first."
)


def _fallback_substituted(requested_model: str, served_model: str | None) -> bool:
    """True if LiteLLM's fallbacks: list silently substituted a different
    deployment than the one requested (only expected if the primary errored,
    e.g. a stale/expired OAuth credential for that provider in this dev slot).
    A result affected by this should not be attributed to the requested model."""
    return bool(served_model) and served_model != requested_model


def check_reasoning_tokens(base_url: str, api_key: str, model: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    record: dict = {"model": model, "check": "reasoning_tokens"}

    # 1. Plain chat/completions usage shape.
    try:
        r = httpx.post(
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json={
                "model": f"AI-Gateway:{model}",
                "messages": [{"role": "user", "content": REASONING_PROMPT}],
                "reasoning_effort": "medium",
            },
            timeout=60,
        )
        record["chat_completions_status"] = r.status_code
        if r.status_code == 200:
            body = r.json()
            served_model = body.get("model")
            record["chat_completions_served_model"] = served_model
            record["chat_completions_fallback_substituted"] = _fallback_substituted(model, served_model)
            usage = body.get("usage", {})
            record["chat_completions_usage"] = usage
            details = usage.get("completion_tokens_details", {}) or {}
            record["chat_completions_reasoning_tokens"] = details.get("reasoning_tokens")
        else:
            record["chat_completions_body"] = r.text[:500]
    except httpx.HTTPError as e:
        record["chat_completions_error"] = str(e)

    # 2. Codex Responses API shape (the path with the known hardcoded 0).
    try:
        r = httpx.post(
            f"{base_url}/v1/responses",
            headers=headers,
            json={
                "model": f"AI-Gateway:{model}",
                "input": REASONING_PROMPT,
                "reasoning": {"effort": "medium"},
            },
            timeout=60,
        )
        record["responses_status"] = r.status_code
        if r.status_code == 200:
            body = r.json()
            served_model = body.get("model")
            record["responses_served_model"] = served_model
            record["responses_fallback_substituted"] = _fallback_substituted(model, served_model)
            record["responses_output_tokens_details"] = body.get("usage", {}).get("output_tokens_details")
        else:
            record["responses_body"] = r.text[:500]
    except httpx.HTTPError as e:
        record["responses_error"] = str(e)

    return record


def _stream_tool_calls(base_url: str, api_key: str, model: str, prompt: str) -> dict:
    """Shared SSE-accumulation helper for the single- and parallel-tool-call checks.

    Returns a dict with status/error/body on failure, or tool_calls (dict keyed
    by stream index -> {name, arguments}) and saw_finish_tool_calls on success.
    """
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    tool_calls: dict[int, dict] = {}
    saw_finish_tool_calls = False
    served_model = None

    try:
        with httpx.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json={
                "model": f"AI-Gateway:{model}",
                "messages": [{"role": "user", "content": prompt}],
                "tools": [TOOL_SCHEMA],
                "tool_choice": "auto",
                "parallel_tool_calls": True,
                "stream": True,
            },
            timeout=60,
        ) as r:
            if r.status_code != 200:
                return {"status": r.status_code, "body": r.read().decode(errors="replace")[:500]}
            malformed_chunks = []
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: ") :]
                if payload.strip() == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    malformed_chunks.append(payload[:200])
                    continue
                if served_model is None and chunk.get("model"):
                    served_model = chunk["model"]
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta", {})
                if choice.get("finish_reason") == "tool_calls":
                    saw_finish_tool_calls = True
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tool_calls.setdefault(idx, {"name": "", "arguments": ""})
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]
    except httpx.HTTPError as e:
        return {"error": str(e)}

    return {
        "status": 200,
        "tool_calls": tool_calls,
        "saw_finish_tool_calls": saw_finish_tool_calls,
        "malformed_chunks": malformed_chunks,
        "served_model": served_model,
        "fallback_substituted": _fallback_substituted(model, served_model),
    }


def _validate_tool_call_args(tool_calls: dict[int, dict]) -> tuple[bool, list[str]]:
    parsed_ok = True
    parse_errors = []
    required = TOOL_SCHEMA["function"]["parameters"]["required"]
    for idx, slot in tool_calls.items():
        try:
            args = json.loads(slot["arguments"]) if slot["arguments"] else {}
        except json.JSONDecodeError as e:
            parsed_ok = False
            parse_errors.append(f"tool_call[{idx}] args not valid JSON: {e}")
            continue
        missing = [k for k in required if k not in args]
        if missing:
            parsed_ok = False
            parse_errors.append(f"tool_call[{idx}] missing required args: {missing}")
    return parsed_ok, parse_errors


def check_streaming_tool_call(base_url: str, api_key: str, model: str) -> dict:
    record: dict = {"model": model, "check": "streaming_tool_call"}
    result = _stream_tool_calls(base_url, api_key, model, TOOL_PROMPT)
    record.update(result)
    if "error" in result or result.get("status") != 200:
        return record

    tool_calls = result["tool_calls"]
    record["tool_calls_seen"] = len(tool_calls)
    parsed_ok, parse_errors = _validate_tool_call_args(tool_calls)
    record["arguments_valid"] = parsed_ok
    record["parse_errors"] = parse_errors
    return record


def check_parallel_tool_calls(base_url: str, api_key: str, model: str) -> dict:
    """Two independent tool calls in the same turn (different cities/units) —
    exercises the same index-keyed delta-accumulation path as a single call,
    but checks whether arguments get scrambled/merged across the two calls
    (the risk flagged against providers/gemini.py's tool_buffers heuristic)."""
    record: dict = {"model": model, "check": "parallel_tool_calls"}
    result = _stream_tool_calls(base_url, api_key, model, PARALLEL_TOOL_PROMPT)
    record.update(result)
    if "error" in result or result.get("status") != 200:
        return record

    tool_calls = result["tool_calls"]
    record["tool_calls_seen"] = len(tool_calls)
    parsed_ok, parse_errors = _validate_tool_call_args(tool_calls)

    cities_seen = []
    for idx, slot in tool_calls.items():
        try:
            args = json.loads(slot["arguments"]) if slot["arguments"] else {}
        except json.JSONDecodeError:
            continue
        cities_seen.append(args.get("city"))

    # Two calls with the same (or missing) city means arguments were scrambled
    # or one call's args leaked into the other — a real integrity failure even
    # if each call's JSON parses fine on its own.
    distinct_cities = len(set(c for c in cities_seen if c)) == len(tool_calls) and len(tool_calls) > 0
    if len(tool_calls) < 2:
        parse_errors.append(f"expected 2 parallel tool calls, saw {len(tool_calls)}")
        parsed_ok = False
    elif not distinct_cities:
        parse_errors.append(f"tool call arguments not distinct across calls: cities={cities_seen}")
        parsed_ok = False

    record["cities_seen"] = cities_seen
    record["arguments_valid"] = parsed_ok
    record["parse_errors"] = parse_errors
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default="claude-sonnet-4-6,gpt-5-4,gemini-3-flash")
    parser.add_argument("--base-url", default="http://localhost:4010")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--out", default="protocol_checks_results.jsonl")
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    records = []
    with open(args.out, "w") as f:
        for model in models:
            for fn in (check_reasoning_tokens, check_streaming_tool_call, check_parallel_tool_calls):
                print(f"[check] {fn.__name__} model={model}", file=sys.stderr)
                rec = fn(args.base_url, args.api_key, model)
                records.append(rec)
                f.write(json.dumps(rec) + "\n")
                f.flush()

    print("\n## Reasoning-token accounting\n")
    print("| Model | chat/completions reasoning_tokens | responses output_tokens_details | fallback? |")
    print("|---|---|---|---|")
    for rec in records:
        if rec["check"] != "reasoning_tokens":
            continue
        fb = rec.get("chat_completions_fallback_substituted") or rec.get("responses_fallback_substituted")
        fb_note = (
            f"yes -> {rec.get('chat_completions_served_model') or rec.get('responses_served_model')}" if fb else "-"
        )
        print(
            f"| {rec['model']} | {rec.get('chat_completions_reasoning_tokens')} "
            f"| {rec.get('responses_output_tokens_details')} | {fb_note} |"
        )

    print("\n## Streaming tool-call integrity\n")
    print("| Model | tool_calls seen | arguments valid | fallback? | errors |")
    print("|---|---|---|---|---|")
    for rec in records:
        if rec["check"] != "streaming_tool_call":
            continue
        errs = "; ".join(rec.get("parse_errors", [])) or "-"
        fb_note = f"yes -> {rec.get('served_model')}" if rec.get("fallback_substituted") else "-"
        print(f"| {rec['model']} | {rec.get('tool_calls_seen')} | {rec.get('arguments_valid')} | {fb_note} | {errs} |")

    print("\n## Parallel tool-call integrity\n")
    print("| Model | tool_calls seen | cities seen | arguments valid | fallback? | errors |")
    print("|---|---|---|---|---|---|")
    for rec in records:
        if rec["check"] != "parallel_tool_calls":
            continue
        errs = "; ".join(rec.get("parse_errors", [])) or "-"
        fb_note = f"yes -> {rec.get('served_model')}" if rec.get("fallback_substituted") else "-"
        print(
            f"| {rec['model']} | {rec.get('tool_calls_seen')} | {rec.get('cities_seen')} "
            f"| {rec.get('arguments_valid')} | {fb_note} | {errs} |"
        )

    print(f"\nRaw JSONL log: {args.out}")


if __name__ == "__main__":
    main()
