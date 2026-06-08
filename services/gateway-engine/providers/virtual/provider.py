"""Virtual Provider for deterministic E2E testing and synthetic monitoring."""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from providers.base import ProviderConverter

class VirtualProvider(ProviderConverter):
    """
    A provider that simulates any model behavior without external API calls.
    Supports deterministic responses, latency simulation, and error injection via headers or model naming.
    """

    def req_to_oai(self, model: str, body: dict) -> dict:
        """
        Passes the request through but attaches 'virtual' metadata.
        In a real scenario, this might perform validation or normalization.
        """
        body["_virtual"] = {
            "requested_model": model,
            "received_at": datetime.now(timezone.utc).isoformat()
        }
        return body

    def oai_to_resp(self, oai: dict, model: str) -> dict:
        """
        Generates a synthetic OpenAI-compatible response.
        """
        # Determine behavior based on model name or payload flags
        # Default behavior: Echo
        
        prompt = ""
        messages = oai.get("messages", [])
        if messages:
            prompt = messages[-1].get("content", "")

        resp_id = f"virt-{uuid.uuid4().hex[:8]}"
        created = int(time.time())

        return {
            "id": resp_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"[Virtual Response] I received your prompt: \"{prompt}\"",
                    },
                    "logprobs": None,
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30
            },
            "system_fingerprint": "v1-virtual"
        }

    def simulate_error(self, status_code: int) -> dict:
        """Helper to return standardized error formats for testing failover."""
        return {
            "error": {
                "message": f"Simulated virtual error {status_code}",
                "type": "virtual_error",
                "param": None,
                "code": status_code
            }
        }
