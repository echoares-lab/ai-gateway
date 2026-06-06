"""Shared types for provider format converters."""

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class ResolvedModel:
    requested_model: str
    effective_model: str
    change_reason: str
    severity: str
    tool_capability_assumption: str


ResolveModelFn = Callable[..., ResolvedModel]


class ProviderConverter(Protocol):
    """Bidirectional converter between a provider API and OpenAI Chat Completions."""

    def req_to_oai(self, model: str, body: dict) -> dict: ...

    def oai_to_resp(self, oai: dict, model: str) -> dict: ...
