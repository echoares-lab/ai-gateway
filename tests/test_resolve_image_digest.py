"""Tests for scripts/k3s/resolve_image_digest.py."""

from __future__ import annotations

import io
from unittest import mock

import pytest

from scripts.k3s.resolve_image_digest import (
    ResolveImageDigestError,
    fetch_manifest_digest,
    is_mutable_tag,
    normalize_digest,
    parse_image_reference,
    require_cliproxy_candidate,
    resolve_reference,
)


def test_normalize_digest_accepts_sha256_prefix() -> None:
    value = "sha256:" + "a" * 64
    assert normalize_digest(value) == value


def test_normalize_digest_accepts_hex_only() -> None:
    assert normalize_digest("b" * 64) == f"sha256:{'b' * 64}"


@pytest.mark.parametrize(
    "tag",
    ["latest", "dev", "staging", "main", "LATEST", "feature-latest", "build-dev"],
)
def test_is_mutable_tag_rejects_floating_tags(tag: str) -> None:
    assert is_mutable_tag(tag)


def test_is_mutable_tag_allows_immutable_candidate_tags() -> None:
    assert not is_mutable_tag("6cf6e68")
    assert not is_mutable_tag("upstream-abc-patch-def1234")


def test_require_cliproxy_candidate_rejects_missing() -> None:
    with pytest.raises(ResolveImageDigestError, match="required"):
        require_cliproxy_candidate(None)
    with pytest.raises(ResolveImageDigestError, match="required"):
        require_cliproxy_candidate("   ")


def test_parse_image_reference_splits_repo_and_tag() -> None:
    ref = parse_image_reference("nexus-docker.infra.plexplease.com/cli-proxy-api:abc1234")
    assert ref.registry == "nexus-docker.infra.plexplease.com"
    assert ref.repository == "cli-proxy-api"
    assert ref.reference == "abc1234"


def test_resolve_reference_passes_through_digest() -> None:
    digest = "sha256:" + "c" * 64
    assert (
        resolve_reference(
            "nexus-docker.infra.plexplease.com/cli-proxy-api",
            reference=digest,
        )
        == digest
    )


def test_resolve_reference_rejects_mutable_tag() -> None:
    with pytest.raises(ResolveImageDigestError, match="mutable tag"):
        resolve_reference(
            "nexus-docker.infra.plexplease.com/cli-proxy-api",
            reference="dev",
        )


def test_fetch_manifest_digest_returns_docker_content_digest() -> None:
    digest = "sha256:" + "d" * 64
    response = mock.Mock()
    response.headers = {"Docker-Content-Digest": digest}
    response.__enter__ = mock.Mock(return_value=response)
    response.__exit__ = mock.Mock(return_value=False)

    with mock.patch("urllib.request.urlopen", return_value=response):
        assert fetch_manifest_digest("cli-proxy-api", "abc1234") == digest


def test_fetch_manifest_digest_rejects_missing_digest_header() -> None:
    response = mock.Mock()
    response.headers = {}
    response.__enter__ = mock.Mock(return_value=response)
    response.__exit__ = mock.Mock(return_value=False)

    with mock.patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(ResolveImageDigestError, match="Docker-Content-Digest"):
            fetch_manifest_digest("cli-proxy-api", "abc1234")


def test_fetch_manifest_digest_maps_404_to_candidate_error() -> None:
    import urllib.error

    with mock.patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            url="https://example/v2/cli-proxy-api/manifests/missing",
            code=404,
            msg="Not Found",
            hdrs=mock.Mock(),
            fp=io.BytesIO(b""),
        ),
    ):
        with pytest.raises(ResolveImageDigestError, match="manifest not found"):
            fetch_manifest_digest("cli-proxy-api", "missing")
