"""Mock upstream provider for tool-use benchmark (Epic #420)."""

import asyncio
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()


@app.get("/v1/models")
async def get_models():
    return {
        "data": [
            {"id": "claude-sonnet-4-6", "object": "model", "owned_by": "anthropic"},
            {"id": "gpt-5-4", "object": "model", "owned_by": "openai"},
            {"id": "gemini-3-flash", "object": "model", "owned_by": "google"},
        ]
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "")
    messages = body.get("messages", [])
    streaming = body.get("stream", False)
    tools = body.get("tools", [])
    print(f"DEBUG Upstream got tools: {json.dumps(tools)}")
    print(f"DEBUG Upstream got messages: {json.dumps(messages)}")

    # Find the user's prompt
    user_prompt = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                user_prompt = content
            elif isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        user_prompt += part.get("text", "")
            break

    # Mock tool response logic based on task prompts and target models
    args = {}
    tool_name = ""
    tool_call_id = ""

    if "replace 'Hello' with 'Bonjour'" in user_prompt:
        # Check if Read tool result exists in messages
        has_been_read = False
        for msg in messages:
            if msg.get("role") == "tool" and msg.get("tool_call_id") == "call_read_file":
                has_been_read = True
                break

        import re

        abs_path = "file.txt"
        match = re.search(r"(/[^\s]+/file\.txt)", user_prompt)
        if match:
            abs_path = match.group(1)

        if not has_been_read:
            tool_name = "Read"
            tool_call_id = "call_read_file"
            args = {"file_path": abs_path}
        else:
            tool_name = "Edit"
            tool_call_id = "call_single_edit"
            if "gemini" in model:
                # Simulate spacing/exact match failure on Gemini
                args = {"file_path": abs_path, "old_string": "Hello ", "new_string": "Bonjour"}
            else:
                args = {"file_path": abs_path, "old_string": "Hello", "new_string": "Bonjour"}

    elif "new.txt" in user_prompt:
        tool_name = "Write"
        tool_call_id = "call_new_file"
        import re

        abs_path = "new.txt"
        match = re.search(r"(/[^\s]+/new\.txt)", user_prompt)
        if match:
            abs_path = match.group(1)
        args = {"file_path": abs_path, "content": "Welcome to AI Gateway"}

    # Handle streaming
    if streaming and tool_name:

        async def event_generator():
            # Initial delta
            yield 'data: {"choices": [{"delta": {"role": "assistant"}, "index": 0, "finish_reason": null}]}\n\n'
            await asyncio.sleep(0.01)

            # Send tool call start (name)
            yield f'data: {{"choices": [{{"delta": {{"tool_calls": [{{"index": 0, "id": "{tool_call_id}", "type": "function", "function": {{"name": "{tool_name}"}}}}], "role": "assistant"}}, "index": 0, "finish_reason": null}}]}}\n\n'
            await asyncio.sleep(0.01)

            # Chunk arguments
            args_str = json.dumps(args)
            chunk_size = 10
            for i in range(0, len(args_str), chunk_size):
                chunk = args_str[i : i + chunk_size]
                escaped_chunk = json.dumps(chunk)[1:-1]
                yield f'data: {{"choices": [{{"delta": {{"tool_calls": [{{"index": 0, "function": {{"arguments": "{escaped_chunk}"}}}}]}}, "index": 0, "finish_reason": null}}]}}\n\n'
                await asyncio.sleep(0.02)

            # Finish tool call
            yield 'data: {"choices": [{"delta": {}, "index": 0, "finish_reason": "tool_calls"}]}\n\n'
            await asyncio.sleep(0.01)
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Non-streaming fallback / text completion response
    if tool_name:
        tool_call = {
            "id": tool_call_id,
            "type": "function",
            "function": {"name": tool_name, "arguments": json.dumps(args)},
        }
        return JSONResponse(
            status_code=200,
            content={
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            },
        )

    # Simple text response
    return JSONResponse(
        status_code=200,
        content={
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Task completed successfully."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=5001)
