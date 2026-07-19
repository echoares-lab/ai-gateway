#!/usr/bin/env python3
"""Direct gateway protocol checks — no client CLI involved.

Tests the two gaps identified against docs/FEATURE_CANDIDATES.md C-RT-6:
  1. Reasoning-token usage accounting on /v1/chat/completions vs the Codex
     /v1/responses shape (proxy_responses.py hardcodes
     output_tokens_details.reasoning_tokens to 0 — this check confirms
     whether that's still true and whether the underlying chat-completions
     usage actually carries a real value that's being discarded).
  2. Streaming tool-call delta integrity on /v1/chat/completions: accumulate
     SSE tool-call argument deltas and confirm they parse as valid JSON
     matching the tool schema, per model.

See docs/tool-use-eval.md and scripts/eval/README.md for context.
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
            usage = r.json().get("usage", {})
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
            record["responses_output_tokens_details"] = body.get("usage", {}).get("output_tokens_details")
        else:
            record["responses_body"] = r.text[:500]
    except httpx.HTTPError as e:
        record["responses_error"] = str(e)

    return record


def check_streaming_tool_call(base_url: str, api_key: str, model: str) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    record: dict = {"model": model, "check": "streaming_tool_call"}

    tool_calls: dict[int, dict] = {}
    saw_finish_tool_calls = False
    try:
        with httpx.stream(
            "POST",
            f"{base_url}/v1/chat/completions",
            headers=headers,
            json={
                "model": f"AI-Gateway:{model}",
                "messages": [{"role": "user", "content": TOOL_PROMPT}],
                "tools": [TOOL_SCHEMA],
                "tool_choice": "auto",
                "stream": True,
            },
            timeout=60,
        ) as r:
            record["status"] = r.status_code
            if r.status_code != 200:
                record["body"] = r.read().decode(errors="replace")[:500]
                return record
            for line in r.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: ") :]
                if payload.strip() == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    record.setdefault("malformed_chunks", []).append(payload[:200])
                    continue
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
        record["error"] = str(e)
        return record

    record["saw_finish_tool_calls"] = saw_finish_tool_calls
    record["tool_calls_seen"] = len(tool_calls)
    parsed_ok = True
    parse_errors = []
    for idx, slot in tool_calls.items():
        try:
            args = json.loads(slot["arguments"]) if slot["arguments"] else {}
        except json.JSONDecodeError as e:
            parsed_ok = False
            parse_errors.append(f"tool_call[{idx}] args not valid JSON: {e}")
            continue
        required = TOOL_SCHEMA["function"]["parameters"]["required"]
        missing = [k for k in required if k not in args]
        if missing:
            parsed_ok = False
            parse_errors.append(f"tool_call[{idx}] missing required args: {missing}")
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
            for fn in (check_reasoning_tokens, check_streaming_tool_call):
                print(f"[check] {fn.__name__} model={model}", file=sys.stderr)
                rec = fn(args.base_url, args.api_key, model)
                records.append(rec)
                f.write(json.dumps(rec) + "\n")
                f.flush()

    print("\n## Reasoning-token accounting\n")
    print("| Model | chat/completions reasoning_tokens | responses output_tokens_details |")
    print("|---|---|---|")
    for rec in records:
        if rec["check"] != "reasoning_tokens":
            continue
        print(
            f"| {rec['model']} | {rec.get('chat_completions_reasoning_tokens')} "
            f"| {rec.get('responses_output_tokens_details')} |"
        )

    print("\n## Streaming tool-call integrity\n")
    print("| Model | tool_calls seen | arguments valid | errors |")
    print("|---|---|---|---|")
    for rec in records:
        if rec["check"] != "streaming_tool_call":
            continue
        errs = "; ".join(rec.get("parse_errors", [])) or "-"
        print(f"| {rec['model']} | {rec.get('tool_calls_seen')} | {rec.get('arguments_valid')} | {errs} |")

    print(f"\nRaw JSONL log: {args.out}")


if __name__ == "__main__":
    main()
