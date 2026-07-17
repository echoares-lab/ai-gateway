"""Tests for scripts/k3s/promote_k3s_images.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.k3s.promote_k3s_images import _set_gateway_version, _set_image_pin, main, require_cliproxy_digest_pin
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
