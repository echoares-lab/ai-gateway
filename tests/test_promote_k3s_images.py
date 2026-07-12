"""Tests for scripts/k3s/promote_k3s_images.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.k3s.promote_k3s_images import _set_image_pin, main


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


def test_main_updates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "k3s-01"
    overlay = repo / "kubernetes/workloads/home/ai-gateway/overlays/k3s-01"
    overlay.mkdir(parents=True)
    path = overlay / "kustomization.yaml"
    path.write_text(FIXTURE, encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "scripts/k3s/promote_k3s_images.py",
            "--k3s-repo",
            str(repo),
            "--gateway-engine",
            "deadbee",
            "--credential-prober",
            "cafebabe",
        ],
    )
    assert main() == 0
    text = path.read_text(encoding="utf-8")
    assert 'newTag: "deadbee"' in text
    assert 'newTag: "cafebabe"' in text
