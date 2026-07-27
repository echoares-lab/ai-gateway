"""Tests for scripts/k3s/promote_k3s_images.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.k3s.promote_k3s_images import (
    _gateway_workload_path,
    _litellm_manifest_paths,
    _pin_file_for_image,
    _set_gateway_version,
    _set_image_pin,
    _set_litellm_image,
    main,
    require_cliproxy_digest_pin,
)
from scripts.k3s.resolve_image_digest import ResolveImageDigestError

FIXTURE = """apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
images:
  - name: nexus-docker.infra.plexplease.com/cli-proxy-api
    newTag: "6cf6e68"
  - name: nexus-docker.infra.plexplease.com/ai-gateway/gateway-engine
    newTag: "d4a621b"
  - name: nexus-docker.infra.plexplease.com/ai-gateway/credential-prober
    digest: sha256:6193e710b4992d6e6feb71959da25f93259697bd844f382f4e3916facf867540
  - name: nexus-docker.infra.plexplease.com/ai-gateway/docs-server
    digest: sha256:8709f4f019a32a4195dfd5b973585f704d8066a28b1c41b4b22b53826cb0ce33
"""

WORKLOAD_FIXTURE = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: gateway-engine
  namespace: ai-gateway
  labels:
    app.kubernetes.io/version: 1.2.0
spec:
  selector: { matchLabels: { app: gateway-engine } }
  template:
    metadata:
      labels:
        app: gateway-engine
        app.kubernetes.io/version: 1.2.0
"""

COMPONENT_PIN = """apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - cliproxy.yaml
images:
  - name: nexus-docker.infra.plexplease.com/cli-proxy-api
    digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""


def test_set_image_pin_tag() -> None:
    out = _set_image_pin(
        FIXTURE,
        "nexus-docker.infra.plexplease.com/ai-gateway/gateway-engine",
        tag="abc1234",
        digest=None,
    )
    assert 'newTag: "abc1234"' in out
    assert "d4a621b" not in out


def test_set_image_pin_digest_from_tag() -> None:
    out = _set_image_pin(
        FIXTURE,
        "nexus-docker.infra.plexplease.com/ai-gateway/gateway-engine",
        tag=None,
        digest="sha256:1111111111111111111111111111111111111111111111111111111111111111",
    )
    assert "digest: sha256:1111111111111111111111111111111111111111111111111111111111111111" in out
    assert "gateway-engine" in out
    assert 'newTag: "d4a621b"' not in out


def test_set_image_pin_cliproxy_digest() -> None:
    digest = "sha256:" + "e" * 64
    out = _set_image_pin(
        FIXTURE,
        "nexus-docker.infra.plexplease.com/cli-proxy-api",
        tag=None,
        digest=digest,
    )
    assert f"digest: {digest}" in out
    assert 'newTag: "6cf6e68"' not in out


def test_require_cliproxy_digest_pin_rejects_tag() -> None:
    with pytest.raises(ResolveImageDigestError, match="immutable sha256 digests"):
        require_cliproxy_digest_pin("6cf6e68")


def test_require_cliproxy_digest_pin_rejects_missing() -> None:
    with pytest.raises(ResolveImageDigestError, match="required"):
        require_cliproxy_digest_pin(None)


def test_require_cliproxy_digest_pin_accepts_digest() -> None:
    digest = "sha256:" + "f" * 64
    assert require_cliproxy_digest_pin(digest) == digest


def test_set_gateway_version_updates_deployment_and_pod_without_selector() -> None:
    out = _set_gateway_version(WORKLOAD_FIXTURE, "1.2.1")

    assert out.count("app.kubernetes.io/version: 1.2.1") == 2
    assert "app.kubernetes.io/version: 1.2.0" not in out
    assert "selector: { matchLabels: { app: gateway-engine } }" in out


@pytest.mark.parametrize("version", ["v1.2.1", "1.2", "1.2.1+build", "latest"])
def test_set_gateway_version_rejects_non_label_semver(version: str) -> None:
    with pytest.raises(ValueError, match="SemVer core"):
        _set_gateway_version(WORKLOAD_FIXTURE, version)


def test_set_litellm_image() -> None:
    doc = """
- name: litellm
  image: old-image
"""
    assert "image: new-image" in _set_litellm_image(doc, "new-image", "litellm")

    doc_block = """
- name: litellm
  image: >-
    old-image
"""
    assert "new-image" in _set_litellm_image(doc_block, "new-image", "litellm")


def test_pin_file_for_image_prefers_component_subdir(tmp_path: Path) -> None:
    overlay = tmp_path / "overlays" / "k3s-01"
    (overlay / "cliproxy").mkdir(parents=True)
    parent = overlay / "kustomization.yaml"
    parent.write_text("apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n", encoding="utf-8")
    component = overlay / "cliproxy" / "kustomization.yaml"
    component.write_text(COMPONENT_PIN, encoding="utf-8")

    assert (
        _pin_file_for_image(parent, "nexus-docker.infra.plexplease.com/cli-proxy-api")
        == component
    )


def test_gateway_workload_path_prefers_split_layout(tmp_path: Path) -> None:
    overlay = tmp_path / "overlays" / "k3s-01"
    (overlay / "gateway-engine").mkdir(parents=True)
    missing = overlay / "core-workloads.yaml"
    split = overlay / "gateway-engine" / "gateway-engine.yaml"
    split.write_text(WORKLOAD_FIXTURE, encoding="utf-8")
    assert _gateway_workload_path(overlay, missing) == split


def test_litellm_manifest_paths_split_layout(tmp_path: Path) -> None:
    overlay = tmp_path / "overlays" / "k3s-01"
    (overlay / "litellm").mkdir(parents=True)
    (overlay / "foundation").mkdir(parents=True)
    deploy = overlay / "litellm" / "litellm.yaml"
    jobs = overlay / "foundation" / "db-jobs.yaml"
    deploy.write_text("- name: litellm\n  image: old\n", encoding="utf-8")
    jobs.write_text("- name: migrate\n  image: old\n", encoding="utf-8")
    assert _litellm_manifest_paths(overlay) == (deploy, jobs)


def test_main_updates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "k3s-01"
    overlay = repo / "kubernetes/workloads/home/ai-gateway/overlays/k3s-01"
    overlay.mkdir(parents=True)
    path = overlay / "kustomization.yaml"
    path.write_text(FIXTURE, encoding="utf-8")
    workload_path = overlay / "core-workloads.yaml"
    workload_path.write_text(WORKLOAD_FIXTURE, encoding="utf-8")
    cliproxy_digest = "sha256:" + "a" * 64

    monkeypatch.setattr(
        "sys.argv",
        [
            "scripts/k3s/promote_k3s_images.py",
            "--k3s-repo",
            str(repo),
            "--gateway-engine",
            "deadbee",
            "--gateway-version",
            "1.2.1",
            "--credential-prober",
            "cafebabe",
            "--cliproxy",
            cliproxy_digest,
        ],
    )
    assert main() == 0
    text = path.read_text(encoding="utf-8")
    assert 'newTag: "deadbee"' in text
    assert 'newTag: "cafebabe"' in text
    assert f"digest: {cliproxy_digest}" in text
    assert 'newTag: "6cf6e68"' not in text
    assert workload_path.read_text(encoding="utf-8").count("app.kubernetes.io/version: 1.2.1") == 2


def test_main_updates_split_component_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "k3s-01"
    overlay = repo / "kubernetes/workloads/home/ai-gateway/overlays/k3s-01"
    for component in ("cliproxy", "gateway-engine", "credential-prober", "docs", "langfuse", "litellm", "foundation"):
        (overlay / component).mkdir(parents=True)

    (overlay / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\nresources:\n  - cliproxy\n",
        encoding="utf-8",
    )

    def write_pin(rel: str, image: str, digest: str) -> Path:
        path = overlay / rel
        path.write_text(
            "apiVersion: kustomize.config.k8s.io/v1beta1\n"
            "kind: Kustomization\n"
            "images:\n"
            f"  - name: {image}\n"
            f"    digest: {digest}\n",
            encoding="utf-8",
        )
        return path

    cliproxy = write_pin(
        "cliproxy/kustomization.yaml",
        "nexus-docker.infra.plexplease.com/cli-proxy-api",
        "sha256:" + "a" * 64,
    )
    gateway = write_pin(
        "gateway-engine/kustomization.yaml",
        "nexus-docker.infra.plexplease.com/ai-gateway/gateway-engine",
        "sha256:" + "b" * 64,
    )
    write_pin(
        "credential-prober/kustomization.yaml",
        "nexus-docker.infra.plexplease.com/ai-gateway/credential-prober",
        "sha256:" + "c" * 64,
    )
    write_pin(
        "docs/kustomization.yaml",
        "nexus-docker.infra.plexplease.com/ai-gateway/docs-server",
        "sha256:" + "d" * 64,
    )
    langfuse = write_pin(
        "langfuse/kustomization.yaml",
        "docker.io/langfuse/langfuse",
        "sha256:" + "e" * 64,
    )
    # second image in same file
    langfuse.write_text(
        langfuse.read_text(encoding="utf-8")
        + "  - name: docker.io/langfuse/langfuse-worker\n"
        + "    digest: sha256:"
        + ("f" * 64)
        + "\n",
        encoding="utf-8",
    )

    workload = overlay / "gateway-engine" / "gateway-engine.yaml"
    workload.write_text(WORKLOAD_FIXTURE, encoding="utf-8")
    litellm_deploy = overlay / "litellm" / "litellm.yaml"
    litellm_deploy.write_text("- name: litellm\n  image: old-litellm\n", encoding="utf-8")
    db_jobs = overlay / "foundation" / "db-jobs.yaml"
    db_jobs.write_text("- name: migrate\n  image: old-litellm\n", encoding="utf-8")

    new_cliproxy = "sha256:" + "1" * 64
    monkeypatch.setattr(
        "sys.argv",
        [
            "scripts/k3s/promote_k3s_images.py",
            "--k3s-repo",
            str(repo),
            "--gateway-engine",
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "--gateway-version",
            "1.2.1",
            "--cliproxy",
            new_cliproxy,
            "--litellm",
            "ghcr.io/berriai/litellm:v1.93.0@sha256:newlitellm",
            "--langfuse",
            "sha256:" + "2" * 64,
        ],
    )
    assert main() == 0

    assert f"digest: {new_cliproxy}" in cliproxy.read_text(encoding="utf-8")
    assert "digest: sha256:deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef" in gateway.read_text(
        encoding="utf-8"
    )
    assert workload.read_text(encoding="utf-8").count("app.kubernetes.io/version: 1.2.1") == 2
    assert "image: ghcr.io/berriai/litellm:v1.93.0@sha256:newlitellm" in litellm_deploy.read_text(encoding="utf-8")
    assert "image: ghcr.io/berriai/litellm:v1.93.0@sha256:newlitellm" in db_jobs.read_text(encoding="utf-8")
    assert "digest: sha256:" + ("2" * 64) in langfuse.read_text(encoding="utf-8")
    # Aggregator must stay image-free.
    assert "images:" not in (overlay / "kustomization.yaml").read_text(encoding="utf-8")


def test_main_updates_ext(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "k3s-01"
    overlay = repo / "kubernetes/workloads/home/ai-gateway/overlays/k3s-01"
    overlay.mkdir(parents=True)
    path = overlay / "kustomization.yaml"

    kust_fixture = """apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
images:
  - name: docker.io/langfuse/langfuse
    newTag: "3.0.0"
  - name: docker.io/langfuse/langfuse-worker
    digest: sha256:2222222222222222222222222222222222222222222222222222222222222222
"""
    path.write_text(kust_fixture, encoding="utf-8")

    workload_path = overlay / "core-workloads.yaml"
    workload_fixture = """
- name: litellm
  image: old-litellm
"""
    workload_path.write_text(workload_fixture, encoding="utf-8")

    db_jobs_path = overlay / "db-jobs.yaml"
    db_jobs_fixture = """
- name: migrate
  image: old-litellm
"""
    db_jobs_path.write_text(db_jobs_fixture, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "scripts/k3s/promote_k3s_images.py",
            "--k3s-repo",
            str(repo),
            "--litellm",
            "sha256:newlitellm",
            "--langfuse",
            "sha256:newweb",
            "--langfuse-worker",
            "sha256:newworker",
        ],
    )
    assert main() == 0
    kust_text = path.read_text(encoding="utf-8")
    assert "digest: sha256:newweb" in kust_text
    assert "digest: sha256:newworker" in kust_text
    assert "image: sha256:newlitellm" in workload_path.read_text(encoding="utf-8")
    assert "image: sha256:newlitellm" in db_jobs_path.read_text(encoding="utf-8")
