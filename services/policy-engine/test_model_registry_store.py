"""Unit tests for read-only model_registry trait access."""

from __future__ import annotations

from model_registry_store import ModelRegistryStore


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def test_traits_for_models_reads_canonical_and_alias_rows():
    conn = FakeConnection(
        [
            (
                "claude-sonnet-4-6",
                "anthropic",
                "anthropic",
                True,
                False,
                2,
                "claude-sonnet",
            )
        ]
    )
    store = ModelRegistryStore(lambda: conn)

    traits = store.traits_for_models(["claude-sonnet", "missing"])

    assert traits["claude-sonnet-4-6"]["family"] == "anthropic"
    assert traits["claude-sonnet"]["canonical_model_id"] == "claude-sonnet-4-6"
    assert traits["claude-sonnet"]["tools"] is True
    assert traits["claude-sonnet"]["vision"] is False
    assert traits["claude-sonnet"]["cost"] == 2
    assert conn.closed is True


def test_traits_for_models_fail_open_on_read_error():
    def broken_connect():
        raise RuntimeError("db down")

    store = ModelRegistryStore(broken_connect)

    assert store.traits_for_models(["claude-sonnet-4-6"]) == {}


def test_traits_for_models_uses_fixtures_without_db():
    store = ModelRegistryStore(
        None,
        enabled=False,
        fixtures={"gpt-5-4": {"family": "openai", "tools": True, "cost": 1}},
    )

    assert store.traits_for_models(["gpt-5-4"]) == {"gpt-5-4": {"family": "openai", "tools": True, "cost": 1}}
