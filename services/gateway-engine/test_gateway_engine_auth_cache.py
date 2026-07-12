"""Auth rewrite and cache-key safety unit tests."""

from __future__ import annotations

import hashlib

import main as t


class TestNormalizeUpstreamAuthorization:
    def test_missing_authorization_sets_routing_key(self, monkeypatch):
        monkeypatch.setenv("LITELLM_ROUTING_KEY", "rk-test")
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        headers: dict = {}
        t._normalize_upstream_authorization(headers)
        assert headers["authorization"] == "Bearer rk-test"

    def test_ak_key_rewritten_to_routing_key(self, monkeypatch):
        monkeypatch.setenv("LITELLM_ROUTING_KEY", "rk-route")
        monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
        headers = {"Authorization": "Bearer ak-t-w-team-repo-env"}
        t._normalize_upstream_authorization(headers)
        assert headers["Authorization"] == "Bearer rk-route"

    def test_ak_key_falls_back_to_master_key(self, monkeypatch):
        monkeypatch.delenv("LITELLM_ROUTING_KEY", raising=False)
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
        headers = {"authorization": "Bearer ak-t-w-team-repo-env"}
        t._normalize_upstream_authorization(headers)
        assert headers["authorization"] == "Bearer sk-master"

    def test_real_bearer_sk_unchanged(self, monkeypatch):
        monkeypatch.setenv("LITELLM_ROUTING_KEY", "rk-route")
        headers = {"Authorization": "Bearer sk-user-key-123"}
        t._normalize_upstream_authorization(headers)
        assert headers["Authorization"] == "Bearer sk-user-key-123"

    def test_empty_routing_key_no_rewrite(self, monkeypatch):
        monkeypatch.setenv("LITELLM_ROUTING_KEY", "")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "")
        headers = {"authorization": "Bearer ak-t-w-team-repo-env"}
        t._normalize_upstream_authorization(headers)
        assert headers["authorization"] == "Bearer ak-t-w-team-repo-env"


class TestCacheKeyAuthFingerprint:
    def test_returns_none_without_auth_fingerprint_when_cache_enabled(self, monkeypatch):
        monkeypatch.setattr(t, "CACHE_ENABLED", True)
        # Pretend redis is connected
        monkeypatch.setattr(t, "_redis", object())
        assert t._cache_key("m", [{"role": "user", "content": "hi"}]) is None
        assert t._cache_key("m", [{"role": "user", "content": "hi"}], auth_fingerprint="") is None
        assert t._cache_key("m", [{"role": "user", "content": "hi"}], auth_fingerprint=None) is None

    def test_includes_auth_fingerprint_in_key(self, monkeypatch):
        monkeypatch.setattr(t, "CACHE_ENABLED", True)
        monkeypatch.setattr(t, "_redis", object())
        fp = hashlib.sha256(b"sk-a").hexdigest()
        key = t._cache_key("m", [{"role": "user", "content": "hi"}], auth_fingerprint=fp)
        assert key is not None
        assert key.startswith("tx:")
        other = t._cache_key(
            "m", [{"role": "user", "content": "hi"}], auth_fingerprint=hashlib.sha256(b"sk-b").hexdigest()
        )
        assert other != key
