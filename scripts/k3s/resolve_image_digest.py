#!/usr/bin/env python3
"""Resolve a Nexus/OCI image reference to an immutable sha256 digest.

Rejects missing references and floating tags (latest, dev, staging, …) so
production promotion cannot pin mutable candidates.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_REGISTRY = "nexus-docker.infra.plexplease.com"
DEFAULT_CLIPROXY_IMAGE = f"{DEFAULT_REGISTRY}/cli-proxy-api"

MUTABLE_TAGS = frozenset({"latest", "dev", "staging", "main", "master", "prod", "production"})
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ResolveImageDigestError(ValueError):
    """Candidate reference cannot be promoted."""


@dataclass(frozen=True)
class ImageRef:
    registry: str
    repository: str
    reference: str


def normalize_digest(value: str) -> str:
    value = value.strip()
    if HEX_DIGEST_RE.fullmatch(value):
        return f"sha256:{value}"
    if DIGEST_RE.fullmatch(value):
        return value
    raise ResolveImageDigestError(f"invalid digest: {value!r}")


def is_digest(value: str) -> bool:
    try:
        normalize_digest(value)
        return True
    except ResolveImageDigestError:
        return False


def is_mutable_tag(tag: str) -> bool:
    lowered = tag.strip().lower()
    if lowered in MUTABLE_TAGS:
        return True
    return lowered.endswith("-latest") or lowered.endswith("-dev")


def parse_image_reference(image: str, *, reference: str | None = None) -> ImageRef:
    image = image.strip()
    if not image:
        raise ResolveImageDigestError("image reference is required")

    if reference is None:
        if "@" in image:
            repo, ref = image.rsplit("@", 1)
            return _split_repo(repo, ref)
        if ":" in image and not image.endswith(":"):
            repo, ref = image.rsplit(":", 1)
            return _split_repo(repo, ref)
        raise ResolveImageDigestError(f"image reference must include a tag or digest: {image!r}")

    return _split_repo(image, reference.strip())


def _split_repo(repository: str, reference: str) -> ImageRef:
    if not reference:
        raise ResolveImageDigestError("tag or digest reference is required")
    if "/" not in repository:
        raise ResolveImageDigestError(f"invalid repository: {repository!r}")
    registry, _, name = repository.partition("/")
    if not registry or not name:
        raise ResolveImageDigestError(f"invalid repository: {repository!r}")
    return ImageRef(registry=registry, repository=name, reference=reference)


def require_cliproxy_candidate(candidate: str | None) -> str:
    if not candidate or not candidate.strip():
        raise ResolveImageDigestError("cliproxy candidate is required for promotion")
    return candidate.strip()


def resolve_reference(
    image: str,
    *,
    reference: str | None = None,
    registry: str = DEFAULT_REGISTRY,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Return sha256 digest for image@tag; pass through existing digests."""
    require_cliproxy_candidate(reference or image)
    parsed = parse_image_reference(image, reference=reference)

    if is_digest(parsed.reference):
        return normalize_digest(parsed.reference)

    tag = parsed.reference
    if is_mutable_tag(tag):
        raise ResolveImageDigestError(f"mutable tag {tag!r} cannot be promoted; pin an immutable candidate")

    return fetch_manifest_digest(
        parsed.repository,
        tag,
        registry=parsed.registry or registry,
        username=username,
        password=password,
    )


def fetch_manifest_digest(
    repository: str,
    tag: str,
    *,
    registry: str = DEFAULT_REGISTRY,
    username: str | None = None,
    password: str | None = None,
) -> str:
    if is_mutable_tag(tag):
        raise ResolveImageDigestError(f"mutable tag {tag!r} cannot be promoted")

    url = f"https://{registry}/v2/{repository}/manifests/{tag}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": (
                "application/vnd.docker.distribution.manifest.v2+json,"
                "application/vnd.docker.distribution.manifest.list.v2+json,"
                "application/vnd.oci.image.index.v1+json,"
                "application/vnd.oci.image.manifest.v1+json"
            )
        },
        method="GET",
    )
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            digest = response.headers.get("Docker-Content-Digest")
            if digest and DIGEST_RE.fullmatch(digest):
                return digest
            raise ResolveImageDigestError(
                f"registry did not return Docker-Content-Digest for {registry}/{repository}:{tag}"
            )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ResolveImageDigestError(f"manifest not found for {registry}/{repository}:{tag}") from exc
        raise ResolveImageDigestError(
            f"registry lookup failed for {registry}/{repository}:{tag}: HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ResolveImageDigestError(
            f"registry lookup failed for {registry}/{repository}:{tag}: {exc.reason}"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        default=DEFAULT_CLIPROXY_IMAGE,
        help=f"Repository (default: {DEFAULT_CLIPROXY_IMAGE})",
    )
    parser.add_argument(
        "--reference",
        required=True,
        help="Immutable candidate tag or sha256 digest (not latest/dev)",
    )
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    args = parser.parse_args()

    username = os.environ.get("NEXUS_USERNAME")
    password = os.environ.get("NEXUS_PASSWORD")

    try:
        digest = resolve_reference(
            args.image,
            reference=args.reference,
            registry=args.registry,
            username=username,
            password=password,
        )
    except ResolveImageDigestError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
