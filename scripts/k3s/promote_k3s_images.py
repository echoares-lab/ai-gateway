#!/usr/bin/env python3
"""Update immutable image pins in the k3s-01 ai-gateway overlay.

Edits kubernetes/workloads/home/ai-gateway/overlays/k3s-01/kustomization.yaml
`images:` entries so ArgoCD sees a Git diff and rolls out new tags/digests.

Usage:
  python3 scripts/k3s/promote_k3s_images.py \\
    --k3s-repo /path/to/k3s-01 \\
    --gateway-engine 0123456789abcdef0123456789abcdef01234567 \\
    --gateway-version 1.2.1 \\
    --credential-prober sha256:abc... \\
    --docs-server sha256:def... \\
    --cliproxy 6cf6e68
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from scripts.k3s.resolve_image_digest import (
    ResolveImageDigestError,
    is_digest,
    require_cliproxy_candidate,
)

DEFAULT_REL = Path("kubernetes/workloads/home/ai-gateway/overlays/k3s-01/kustomization.yaml")
DEFAULT_WORKLOAD_REL = Path("kubernetes/workloads/home/ai-gateway/overlays/k3s-01/core-workloads.yaml")

IMAGE_KEYS = {
    "cliproxy": "nexus-docker.infra.plexplease.com/cli-proxy-api",
    "gateway-engine": "nexus-docker.infra.plexplease.com/ai-gateway/gateway-engine",
    "credential-prober": "nexus-docker.infra.plexplease.com/ai-gateway/credential-prober",
    "docs-server": "nexus-docker.infra.plexplease.com/ai-gateway/docs-server",
}


def require_cliproxy_digest_pin(value: str | None) -> str:
    """Production promotion requires an immutable cliproxy digest."""
    candidate = require_cliproxy_candidate(value)
    if not is_digest(candidate):
        raise ResolveImageDigestError("cliproxy production pins must be immutable sha256 digests, not tags")
    return candidate


def _set_image_pin(text: str, image_name: str, *, tag: str | None, digest: str | None) -> str:
    if bool(tag) == bool(digest):
        raise ValueError(f"{image_name}: set exactly one of tag or digest")
    if digest and not digest.startswith("sha256:"):
        digest = f"sha256:{digest}"

    # Match a single images: list entry for this name (newTag or digest form).
    pattern = re.compile(
        rf"(  - name: {re.escape(image_name)}\n)"
        rf"(?:    newTag: \"[^\"]+\"\n|    digest: sha256:[0-9a-f]+\n)",
        re.MULTILINE,
    )
    replacement = f"  - name: {image_name}\n"
    if tag:
        replacement += f'    newTag: "{tag}"\n'
    else:
        replacement += f"    digest: {digest}\n"

    new_text, n = pattern.subn(replacement, text, count=1)
    if n != 1:
        raise RuntimeError(f"failed to update image pin for {image_name} (matches={n})")
    return new_text


def _set_gateway_version(text: str, version: str) -> str:
    """Update only Gateway Engine Deployment and pod-template version labels."""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("gateway version must be a Kubernetes-label-safe SemVer core")

    deployment_pattern = re.compile(
        r"(apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: gateway-engine\n.*?)"
        r"(?=\n---|\Z)",
        re.DOTALL,
    )
    match = deployment_pattern.search(text)
    if match is None:
        raise RuntimeError("failed to find gateway-engine Deployment")

    deployment = match.group(1)
    updated, count = re.subn(
        r"app\.kubernetes\.io/version: [^\s]+",
        f"app.kubernetes.io/version: {version}",
        deployment,
    )
    if count != 2:
        raise RuntimeError(f"expected two gateway-engine version labels, found {count}")
    return text[: match.start(1)] + updated + text[match.end(1) :]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k3s-repo", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, default=DEFAULT_REL)
    parser.add_argument("--workloads", type=Path, default=DEFAULT_WORKLOAD_REL)
    parser.add_argument("--cliproxy", help="required sha256 digest for production promotion")
    parser.add_argument("--gateway-engine")
    parser.add_argument("--gateway-version")
    parser.add_argument("--credential-prober", help="short sha tag OR sha256:digest")
    parser.add_argument("--docs-server", help="short sha tag OR sha256:digest")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = args.k3s_repo / args.overlay
    if not path.is_file():
        print(f"missing overlay file: {path}", file=sys.stderr)
        return 2

    text = path.read_text(encoding="utf-8")
    workload_path = args.k3s_repo / args.workloads
    updates: list[tuple[str, str | None, str | None]] = []

    def add(key: str, value: str | None) -> None:
        if not value:
            return
        if value.startswith("sha256:") or (len(value) == 64 and all(c in "0123456789abcdef" for c in value)):
            updates.append((IMAGE_KEYS[key], None, value))
        else:
            updates.append((IMAGE_KEYS[key], value, None))

    cliproxy_digest: str | None = None
    if args.cliproxy:
        cliproxy_digest = require_cliproxy_digest_pin(args.cliproxy)
    add("cliproxy", cliproxy_digest)
    add("gateway-engine", args.gateway_engine)
    add("credential-prober", args.credential_prober)
    add("docs-server", args.docs_server)

    if not updates:
        print("no image updates requested", file=sys.stderr)
        return 2

    for image_name, tag, digest in updates:
        text = _set_image_pin(text, image_name, tag=tag, digest=digest)

    workload_text: str | None = None
    if args.gateway_version:
        if not workload_path.is_file():
            print(f"missing workloads file: {workload_path}", file=sys.stderr)
            return 2
        workload_text = _set_gateway_version(workload_path.read_text(encoding="utf-8"), args.gateway_version)

    if args.dry_run:
        sys.stdout.write(text)
        return 0

    path.write_text(text, encoding="utf-8")
    if workload_text is not None:
        workload_path.write_text(workload_text, encoding="utf-8")
    print(f"updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
