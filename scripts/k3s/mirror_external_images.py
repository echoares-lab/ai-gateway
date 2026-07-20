#!/usr/bin/env python3
"""Mirror external image pin changes from docker-compose.yml to k3s-01 staging.

This script parses docker-compose.yml to extract the image strings for
litellm, langfuse (langfuse-web), and langfuse-worker. It then compares them
against the images in the parent commit (git show HEAD~1:docker-compose.yml).
If any changes are detected (or if the --force flag is specified), it updates
the corresponding staging manifest files in the k3s-01 repository.

Target staging files in k3s-01:
- litellm in:
  - kubernetes/workloads/home/ai-gateway/overlays/staging/core-workloads.yaml
  - kubernetes/workloads/home/ai-gateway/overlays/staging/db-jobs.yaml
- langfuse in:
  - kubernetes/workloads/home/ai-gateway/overlays/staging/observability.yaml
- langfuse-worker in:
  - kubernetes/workloads/home/ai-gateway/overlays/staging/observability.yaml

Usage:
  python3 scripts/k3s/mirror_external_images.py --k3s-repo /path/to/k3s-01 [--force]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

STAGING_REL_DIR = Path("kubernetes/workloads/home/ai-gateway/overlays/staging")


def split_yaml_docs(content: str) -> list[tuple[str, str]]:
    """Split a YAML file into documents, preserving formatting and separators."""
    pattern = re.compile(r"^---[ \t]*(?:#.*)?$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return [(content, "")]

    docs = []
    last_pos = 0
    for m in matches:
        start, end = m.span()
        docs.append((content[last_pos:start], content[start:end]))
        last_pos = end
    docs.append((content[last_pos:], ""))
    return docs


def get_resource_name(doc: str) -> str | None:
    """Extract metadata.name from a YAML document string."""
    match = re.search(r"^metadata:\s*\n((?:[ \t]+.*\n)*)", doc, re.MULTILINE)
    if not match:
        return None
    metadata_content = match.group(1)
    name_match = re.search(r'^[ \t]+name:[ \t]*["\']?([^"\'\s\n]+)["\']?', metadata_content, re.MULTILINE)
    if name_match:
        return name_match.group(1)
    return None


def update_container_image(doc: str, container_name: str, new_image: str) -> tuple[str, bool]:
    """Update the image field for a container inside a YAML document string.

    Supports block scalars (image: >- \n image_name) and single-line forms.
    """
    # 1. Try block scalar pattern (e.g. image: >- \n   docker.io/...)
    pattern_block = re.compile(
        r"(-\s+name:\s*"
        + re.escape(container_name)
        + r"\b(?:[ \t]*\n|[^-\n].*\n)*?[ \t]+image:\s*>\-\s*\n[ \t]+)([^\s\n]+)"
    )
    if pattern_block.search(doc):
        updated, count = pattern_block.subn(r"\g<1>" + new_image, doc)
        return updated, count > 0

    # 2. Try simple pattern (e.g. image: docker.io/...)
    pattern_simple = re.compile(
        r"(-\s+name:\s*" + re.escape(container_name) + r"\b(?:[ \t]*\n|[^-\n].*\n)*?[ \t]+image:\s*)([^\s\n]+)"
    )
    if pattern_simple.search(doc):
        updated, count = pattern_simple.subn(r"\g<1>" + new_image, doc)
        return updated, count > 0

    return doc, False


def update_manifest_file(file_path: Path, resource_name: str, container_name: str, new_image: str) -> bool:
    """Updates the specified container image in a specific resource within a YAML file."""
    if not file_path.is_file():
        print(f"Error: Target manifest file not found: {file_path}", file=sys.stderr)
        return False

    content = file_path.read_text(encoding="utf-8")
    docs = split_yaml_docs(content)

    updated_any = False
    new_docs = []
    for doc_content, separator in docs:
        name = get_resource_name(doc_content)
        if name == resource_name:
            updated_doc, success = update_container_image(doc_content, container_name, new_image)
            if success:
                doc_content = updated_doc
                updated_any = True
        new_docs.append((doc_content, separator))

    if updated_any:
        new_content = "".join(doc + sep for doc, sep in new_docs)
        file_path.write_text(new_content, encoding="utf-8")
        print(f"Updated {container_name} image in {file_path.name} to: {new_image}")
        return True

    print(f"Warning: Resource {resource_name} or container {container_name} not found in {file_path.name}")
    return False


def parse_compose_images(compose_content: str) -> dict[str, str]:
    """Parse image strings from docker-compose.yml contents."""
    data = yaml.safe_load(compose_content) or {}
    services = data.get("services", {})

    images = {}
    # litellm
    if "litellm" in services and "image" in services["litellm"]:
        images["litellm"] = services["litellm"]["image"]

    # langfuse (corresponds to langfuse-web service in compose)
    if "langfuse-web" in services and "image" in services["langfuse-web"]:
        images["langfuse"] = services["langfuse-web"]["image"]

    # langfuse-worker
    if "langfuse-worker" in services and "image" in services["langfuse-worker"]:
        images["langfuse-worker"] = services["langfuse-worker"]["image"]

    return images


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k3s-repo", type=Path, required=True, help="Path to the k3s-01 repository root")
    parser.add_argument(
        "--force", action="store_true", help="Force mirroring of all images regardless of changes in git history"
    )
    args = parser.parse_args()

    # 1. Read current docker-compose.yml
    compose_path = Path("docker-compose.yml")
    if not compose_path.is_file():
        print("Error: docker-compose.yml not found in the current directory.", file=sys.stderr)
        return 1

    try:
        current_content = compose_path.read_text(encoding="utf-8")
        current_images = parse_compose_images(current_content)
    except Exception as e:
        print(f"Error parsing current docker-compose.yml: {e}", file=sys.stderr)
        return 1

    # Verify all expected keys are present
    required_keys = ["litellm", "langfuse", "langfuse-worker"]
    for key in required_keys:
        if key not in current_images:
            print(f"Error: Missing image configuration for '{key}' in current docker-compose.yml.", file=sys.stderr)
            return 1

    # 2. Retrieve parent docker-compose.yml (git show HEAD~1:docker-compose.yml)
    parent_images = {}
    try:
        parent_content = subprocess.check_output(
            ["git", "show", "HEAD~1:docker-compose.yml"], stderr=subprocess.PIPE, text=True
        )
        parent_images = parse_compose_images(parent_content)
    except subprocess.CalledProcessError:
        print("Warning: Could not retrieve parent commit's docker-compose.yml. Fallback to --force mode behavior.")
        args.force = True
    except Exception as e:
        print(f"Warning: Error parsing parent commit's docker-compose.yml: {e}. Fallback to --force mode behavior.")
        args.force = True

    # 3. Process updates
    updates_made = 0

    # Litellm updates
    litellm_changed = args.force or current_images["litellm"] != parent_images.get("litellm")
    if litellm_changed:
        print(f"litellm image changed from '{parent_images.get('litellm')}' to '{current_images['litellm']}'")

        # update core-workloads.yaml (resource: litellm, container: litellm)
        core_workloads = args.k3s_repo / STAGING_REL_DIR / "core-workloads.yaml"
        if update_manifest_file(core_workloads, "litellm", "litellm", current_images["litellm"]):
            updates_made += 1

        # update db-jobs.yaml (resource: ai-gateway-staging-litellm-migrate, container: migrate)
        db_jobs = args.k3s_repo / STAGING_REL_DIR / "db-jobs.yaml"
        if update_manifest_file(db_jobs, "ai-gateway-staging-litellm-migrate", "migrate", current_images["litellm"]):
            updates_made += 1

    # Langfuse updates
    langfuse_changed = args.force or current_images["langfuse"] != parent_images.get("langfuse")
    if langfuse_changed:
        print(f"langfuse image changed from '{parent_images.get('langfuse')}' to '{current_images['langfuse']}'")

        # update observability.yaml (resource: langfuse-web, container: langfuse-web)
        observability = args.k3s_repo / STAGING_REL_DIR / "observability.yaml"
        if update_manifest_file(observability, "langfuse-web", "langfuse-web", current_images["langfuse"]):
            updates_made += 1

    # Langfuse-worker updates
    langfuse_worker_changed = args.force or current_images["langfuse-worker"] != parent_images.get("langfuse-worker")
    if langfuse_worker_changed:
        print(
            f"langfuse-worker image changed from '{parent_images.get('langfuse-worker')}' to '{current_images['langfuse-worker']}'"
        )

        # update observability.yaml (resource: langfuse-worker, container: langfuse-worker)
        observability = args.k3s_repo / STAGING_REL_DIR / "observability.yaml"
        if update_manifest_file(observability, "langfuse-worker", "langfuse-worker", current_images["langfuse-worker"]):
            updates_made += 1

    if updates_made > 0:
        print(f"Successfully mirrored {updates_made} staging image pin configuration(s).")
    else:
        print("No external image changes detected. Staging manifests are up to date.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
