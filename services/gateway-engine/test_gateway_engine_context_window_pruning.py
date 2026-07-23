"""Unit tests for context-window-aware message history pruning (Epic #489 / Issue #490)."""

from __future__ import annotations

from api.proxy_normalize import _estimate_msg_tokens, _prune_messages_for_context_window


def test_estimate_msg_tokens_string_and_list() -> None:
    msg_str = {"role": "user", "content": "Hello " * 100}
    assert _estimate_msg_tokens(msg_str) > 10

    msg_list = {
        "role": "assistant",
        "content": [{"type": "text", "text": "Thought text " * 50}],
    }
    assert _estimate_msg_tokens(msg_list) > 5


def test_prune_messages_below_max_tokens_does_not_prune() -> None:
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    pruned, changed = _prune_messages_for_context_window(messages, max_tokens=10000)
    assert not changed
    assert len(pruned) == 3


def test_prune_messages_exceeding_max_tokens_preserves_system_and_last_user() -> None:
    messages = [
        {"role": "system", "content": "System prompt instructions"},
        {"role": "user", "content": "Old message 1 " * 500},
        {"role": "assistant", "content": "Old response 1 " * 500},
        {"role": "user", "content": "Old message 2 " * 500},
        {"role": "assistant", "content": "Old response 2 " * 500},
        {"role": "user", "content": "Latest user prompt"},
    ]

    pruned, changed = _prune_messages_for_context_window(messages, max_tokens=1000)
    assert changed
    assert len(pruned) < len(messages)
    assert pruned[0]["role"] == "system"
    assert pruned[-1]["content"] == "Latest user prompt"
