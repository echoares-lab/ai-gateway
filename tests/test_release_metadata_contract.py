"""Static contracts for release metadata propagation into images and CI."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_version_file_contains_semver() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version)


def test_gateway_image_declares_release_metadata() -> None:
    dockerfile = (ROOT / "services/gateway-engine/Dockerfile").read_text(encoding="utf-8")
    assert "ARG APP_VERSION=0.0.0-dev" in dockerfile
    assert "ARG GIT_SHA=unknown" in dockerfile
    assert "ARG BUILD_DATE=unknown" in dockerfile
    assert "org.opencontainers.image.version=$APP_VERSION" in dockerfile
    assert "org.opencontainers.image.revision=$GIT_SHA" in dockerfile
    assert "org.opencontainers.image.created=$BUILD_DATE" in dockerfile
    assert 'ENV APP_VERSION=$APP_VERSION' in dockerfile
    assert 'GIT_SHA=$GIT_SHA' in dockerfile


def test_ci_builds_with_full_sha_and_publishes_semver_tag() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert 'GIT_SHA=$(git rev-parse HEAD)' in workflow
    assert 'APP_VERSION=$(tr -d' in workflow
    assert 'grep -Eq \'^[0-9]+\\.[0-9]+\\.[0-9]+$\'' in workflow
    assert "APP_VERSION=${{ env.APP_VERSION }}" in workflow
    assert "BUILD_DATE=${{ env.BUILD_DATE }}" in workflow
    assert "gateway-engine:${{ env.APP_VERSION }}" in workflow
    assert "gateway-engine:${{ env.GIT_SHA }}" in workflow


def test_compose_passes_release_build_args() -> None:
    for name in ("docker-compose.yml", "docker-compose.dev.yml"):
        compose = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        args = compose["services"]["gateway-engine"]["build"]["args"]
        assert args["APP_VERSION"] == "${APP_VERSION:-0.0.0-dev}"
        assert args["GIT_SHA"] == "${GIT_SHA:-unknown}"
        assert args["BUILD_DATE"] == "${BUILD_DATE:-unknown}"


def test_k3s_promotion_installs_pinned_kubectl_before_rendering() -> None:
    workflow = (ROOT / ".github/workflows/promote-k3s-images.yml").read_text(encoding="utf-8")
    setup_index = workflow.index("azure/setup-kubectl@v4")
    version_index = workflow.index("version: v1.34.1", setup_index)
    render_index = workflow.index("kubectl kustomize", version_index)
    assert setup_index < version_index < render_index
