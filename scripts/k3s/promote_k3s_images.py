#!/usr/bin/env python3
"""Update immutable image pins in the k3s-01 ai-gateway overlay.

Supports both layouts:

- Staging (monolithic): ``overlays/staging/kustomization.yaml`` holds all
  ``images:`` entries; workloads live beside it as ``core-workloads.yaml``.
- Production (split, post k3s-01 #147): each Argo Application owns a component
  subdir under ``overlays/k3s-01/<component>/kustomization.yaml``.

Usage:
  python3 scripts/k3s/promote_k3s_images.py \\
    --k3s-repo /path/to/k3s-01 \\
    --gateway-engine 0123456789abcdef0123456789abcdef01234567 \\
    --gateway-version 1.2.1 \\
    --credential-prober sha256:abc... \\
    --docs-server sha256:def... \\
    --cliproxy sha256:...
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from scripts.k3s.resolve_image_digest import (
    ResolveImageDigestError,
    is_digest,
    require_cliproxy_candidate,
    resolve_reference,
)

DEFAULT_REL = Path("kubernetes/workloads/home/ai-gateway/overlays/k3s-01/kustomization.yaml")
DEFAULT_WORKLOAD_REL = Path("kubernetes/workloads/home/ai-gateway/overlays/k3s-01/core-workloads.yaml")

IMAGE_KEYS = {
    "cliproxy": "nexus-docker.infra.plexplease.com/cli-proxy-api",
    "gateway-engine": "nexus-docker.infra.plexplease.com/ai-gateway/gateway-engine",
    "credential-prober": "nexus-docker.infra.plexplease.com/ai-gateway/credential-prober",
    "docs-server": "nexus-docker.infra.plexplease.com/ai-gateway/docs-server",
    "langfuse": "docker.io/langfuse/langfuse",
    "langfuse-worker": "docker.io/langfuse/langfuse-worker",
}

# Relative to the overlay directory (parent of the --overlay kustomization).
# Used when production was split into per-component Applications.
COMPONENT_PIN_REL = {
    IMAGE_KEYS["cliproxy"]: Path("cliproxy/kustomization.yaml"),
    IMAGE_KEYS["gateway-engine"]: Path("gateway-engine/kustomization.yaml"),
    IMAGE_KEYS["credential-prober"]: Path("credential-prober/kustomization.yaml"),
    IMAGE_KEYS["docs-server"]: Path("docs/kustomization.yaml"),
    IMAGE_KEYS["langfuse"]: Path("langfuse/kustomization.yaml"),
    IMAGE_KEYS["langfuse-worker"]: Path("langfuse/kustomization.yaml"),
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


def _pin_file_for_image(overlay_file: Path, image_name: str) -> Path:
    """Return the kustomization that owns ``image_name`` under this overlay."""
    overlay_dir = overlay_file.parent
    rel = COMPONENT_PIN_REL.get(image_name)
    if rel is not None:
        candidate = overlay_dir / rel
        if candidate.is_file():
            content = candidate.read_text(encoding="utf-8")
            if f"name: {image_name}" in content:
                return candidate
    return overlay_file


def _gateway_workload_path(overlay_dir: Path, workloads_arg: Path) -> Path:
    """Locate the Deployment YAML that carries gateway version labels."""
    if workloads_arg.is_file():
        return workloads_arg
    for candidate in (
        overlay_dir / "gateway-engine" / "gateway-engine.yaml",
        overlay_dir / "core-workloads.yaml",
    ):
        if candidate.is_file():
            return candidate
    return workloads_arg


def _litellm_manifest_paths(overlay_dir: Path) -> tuple[Path, Path]:
    """Return (litellm deployment YAML, migrate Job YAML) for this overlay."""
    deploy_candidates = (
        overlay_dir / "litellm" / "litellm.yaml",
        overlay_dir / "core-workloads.yaml",
    )
    jobs_candidates = (
        overlay_dir / "foundation" / "db-jobs.yaml",
        overlay_dir / "db-jobs.yaml",
    )
    deploy = next((p for p in deploy_candidates if p.is_file()), deploy_candidates[-1])
    jobs = next((p for p in jobs_candidates if p.is_file()), jobs_candidates[-1])
    return deploy, jobs


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


def _set_litellm_image(text: str, image_pin: str, container_name: str) -> str:
    """Replace image reference for container_name in YAML text."""
    # 1. Try block scalar form (e.g. image: >- \n   ghcr.io/...)
    pattern_block = re.compile(
        rf"(-\s+name:\s*{re.escape(container_name)}\b(?:[ \t]*\n|[^-\n].*\n)*?[ \t]+image:\s*>\-\s*\n[ \t]+)([^\s\n]+)"
    )
    if pattern_block.search(text):
        new_text, count = pattern_block.subn(rf"\g<1>{image_pin}", text)
        if count > 0:
            return new_text

    # 2. Try simple form (e.g. image: ghcr.io/...)
    pattern_simple = re.compile(
        rf"(-\s+name:\s*{re.escape(container_name)}\b(?:[ \t]*\n|[^-\n].*\n)*?[ \t]+image:\s*)([^\s\n]+)"
    )
    if pattern_simple.search(text):
        new_text, count = pattern_simple.subn(rf"\g<1>{image_pin}", text)
        if count > 0:
            return new_text

    raise RuntimeError(f"failed to find container image for {container_name}")


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
    parser.add_argument("--litellm", help="litellm tag or sha256 digest")
    parser.add_argument("--langfuse", help="langfuse web tag or sha256 digest")
    parser.add_argument("--langfuse-worker", help="langfuse-worker tag or sha256 digest")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = args.k3s_repo / args.overlay
    if not path.is_file():
        print(f"missing overlay file: {path}", file=sys.stderr)
        return 2

    overlay_dir = path.parent
    workload_arg = args.k3s_repo / args.workloads
    updates: list[tuple[str, str | None, str | None]] = []

    def add(key: str, value: str | None) -> None:
        if not value:
            return
        if value.startswith("sha256:") or (len(value) == 64 and all(c in "0123456789abcdef" for c in value)):
            updates.append((IMAGE_KEYS[key], None, value))
        else:
            username = os.environ.get("NEXUS_USERNAME")
            password = os.environ.get("NEXUS_PASSWORD")
            try:
                digest = resolve_reference(IMAGE_KEYS[key], reference=value, username=username, password=password)
                updates.append((IMAGE_KEYS[key], None, digest))
            except Exception as e:
                print(f"Warning: registry lookup failed for {IMAGE_KEYS[key]}:{value} ({e}); falling back to tag")
                updates.append((IMAGE_KEYS[key], value, None))

    cliproxy_digest: str | None = None
    if args.cliproxy:
        cliproxy_digest = require_cliproxy_digest_pin(args.cliproxy)
    add("cliproxy", cliproxy_digest)
    add("gateway-engine", args.gateway_engine)
    add("credential-prober", args.credential_prober)
    add("docs-server", args.docs_server)
    add("langfuse", args.langfuse)
    add("langfuse-worker", args.langfuse_worker)

    if not updates and not args.litellm and not args.gateway_version:
        print("no image updates requested", file=sys.stderr)
        return 2

    file_texts: dict[Path, str] = {}
    for image_name, tag, digest in updates:
        pin_path = _pin_file_for_image(path, image_name)
        if pin_path not in file_texts:
            if not pin_path.is_file():
                print(f"missing pin file for {image_name}: {pin_path}", file=sys.stderr)
                return 2
            file_texts[pin_path] = pin_path.read_text(encoding="utf-8")
        file_texts[pin_path] = _set_image_pin(file_texts[pin_path], image_name, tag=tag, digest=digest)

    workload_path: Path | None = None
    workload_text: str | None = None
    if args.gateway_version:
        workload_path = _gateway_workload_path(overlay_dir, workload_arg)
        if not workload_path.is_file():
            print(f"missing workloads file: {workload_path}", file=sys.stderr)
            return 2
        workload_text = _set_gateway_version(workload_path.read_text(encoding="utf-8"), args.gateway_version)

    litellm_db_jobs_path: Path | None = None
    litellm_db_jobs_text: str | None = None
    litellm_deploy_path: Path | None = None

    if args.litellm:
        litellm_deploy_path, litellm_db_jobs_path = _litellm_manifest_paths(overlay_dir)
        if not litellm_deploy_path.is_file():
            print(f"missing litellm deployment file: {litellm_deploy_path}", file=sys.stderr)
            return 2
        if not litellm_db_jobs_path.is_file():
            print(f"missing db-jobs file: {litellm_db_jobs_path}", file=sys.stderr)
            return 2

        if workload_path == litellm_deploy_path and workload_text is not None:
            base_workload_text = workload_text
        else:
            base_workload_text = litellm_deploy_path.read_text(encoding="utf-8")
        updated_deploy = _set_litellm_image(base_workload_text, args.litellm, "litellm")
        if workload_path == litellm_deploy_path:
            workload_text = updated_deploy
        else:
            file_texts[litellm_deploy_path] = updated_deploy
        litellm_db_jobs_text = _set_litellm_image(
            litellm_db_jobs_path.read_text(encoding="utf-8"), args.litellm, "migrate"
        )

    if args.dry_run:
        # Preserve prior dry-run behavior: print the primary overlay (or first pin file).
        primary = file_texts.get(path)
        if primary is None and file_texts:
            primary = next(iter(file_texts.values()))
        sys.stdout.write(primary or path.read_text(encoding="utf-8"))
        return 0

    for pin_path, text in file_texts.items():
        pin_path.write_text(text, encoding="utf-8")
        print(f"updated {pin_path}")
    if workload_text is not None and workload_path is not None:
        workload_path.write_text(workload_text, encoding="utf-8")
        print(f"updated {workload_path}")
    if litellm_db_jobs_text is not None and litellm_db_jobs_path is not None:
        litellm_db_jobs_path.write_text(litellm_db_jobs_text, encoding="utf-8")
        print(f"updated {litellm_db_jobs_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
