"""Tests for scripts/k3s/mirror_external_images.py."""

from __future__ import annotations

import pytest
from scripts.k3s.mirror_external_images import (
    split_yaml_docs,
    get_resource_name,
    update_container_image,
    parse_compose_images,
)

YAML_DOCS_FIXTURE = """# First doc
apiVersion: apps/v1
kind: Deployment
metadata:
  name: doc-one
---
# Second doc
apiVersion: v1
kind: Service
metadata:
  name: doc-two
---
# Third doc
apiVersion: batch/v1
kind: Job
metadata:
  name: doc-three
"""

COMPOSE_FIXTURE = """
version: '3'
services:
  litellm:
    image: ghcr.io/berriai/litellm:v1.93.0@sha256:litellm_digest
  langfuse-web:
    image: docker.io/langfuse/langfuse:3@sha256:web_digest
  langfuse-worker:
    image: docker.io/langfuse/langfuse-worker:3@sha256:worker_digest
"""

def test_split_yaml_docs() -> None:
    docs = split_yaml_docs(YAML_DOCS_FIXTURE)
    assert len(docs) == 3
    assert "doc-one" in docs[0][0]
    assert "doc-two" in docs[1][0]
    assert "doc-three" in docs[2][0]
    
    # Rejoining should match the original fixture exactly
    rejoined = "".join(doc + sep for doc, sep in docs)
    assert rejoined == YAML_DOCS_FIXTURE

def test_get_resource_name() -> None:
    doc = """
metadata:
  name: my-deployment
  namespace: test
"""
    assert get_resource_name(doc) == "my-deployment"
    
    doc_quoted = """
metadata:
  name: "my-quoted-deployment"
  namespace: test
"""
    assert get_resource_name(doc_quoted) == "my-quoted-deployment"

def test_update_container_image_simple() -> None:
    doc = """
      containers:
        - name: my-container
          image: old-image:latest
          env: []
"""
    updated, success = update_container_image(doc, "my-container", "new-image:v1")
    assert success
    assert "image: new-image:v1" in updated
    assert "old-image:latest" not in updated
    
    # Negative test
    updated_neg, success_neg = update_container_image(doc, "non-existent-container", "new-image:v1")
    assert not success_neg
    assert updated_neg == doc

def test_update_container_image_block_scalar() -> None:
    doc = """
      containers:
        - name: my-container
          image: >-
            old-image:latest
          env: []
"""
    updated, success = update_container_image(doc, "my-container", "new-image:v1")
    assert success
    assert "new-image:v1" in updated
    assert "old-image:latest" not in updated

def test_parse_compose_images() -> None:
    images = parse_compose_images(COMPOSE_FIXTURE)
    assert images["litellm"] == "ghcr.io/berriai/litellm:v1.93.0@sha256:litellm_digest"
    assert images["langfuse"] == "docker.io/langfuse/langfuse:3@sha256:web_digest"
    assert images["langfuse-worker"] == "docker.io/langfuse/langfuse-worker:3@sha256:worker_digest"
