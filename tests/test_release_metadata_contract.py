"""Static contracts for release metadata propagation and CI workflow behavior."""

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
    assert "ENV APP_VERSION=$APP_VERSION" in dockerfile
    assert "GIT_SHA=$GIT_SHA" in dockerfile


def test_ci_builds_with_full_sha_and_publishes_semver_tag() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "GIT_SHA=$(git rev-parse HEAD)" in workflow
    assert "APP_VERSION=$(tr -d" in workflow
    assert "grep -Eq '^[0-9]+\\.[0-9]+\\.[0-9]+$'" in workflow
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
    setup_index = workflow.index("azure/setup-kubectl")
    version_index = workflow.index("version: v1.34.1", setup_index)
    render_index = workflow.index("kubectl kustomize", version_index)
    assert setup_index < version_index < render_index


def test_k3s_promotion_keeps_full_sha_and_updates_gateway_version() -> None:
    workflow = (ROOT / ".github/workflows/promote-k3s-images.yml").read_text(encoding="utf-8")
    assert 'SHA="${RUN_HEAD_SHA}"' in workflow
    assert 'GATEWAY_VERSION="${INPUT_GATEWAY_VERSION:-$(tr -d' in workflow
    assert '--gateway-version "${GATEWAY_VERSION}"' in workflow
    assert "core-workloads.yaml" in workflow


def test_k3s_promotion_installs_verified_gh_before_pr_creation() -> None:
    workflow = (ROOT / ".github/workflows/promote-k3s-images.yml").read_text(encoding="utf-8")
    setup_index = workflow.index("GH_CLI_VERSION=2.46.0")
    checksum_index = workflow.index(
        "c671d450d7c0e95c84fbc6996591fc851d396848acd53e589ee388031cee9330",
        setup_index,
    )
    verify_index = workflow.index("gh --version", checksum_index)
    create_index = workflow.index("gh pr create", verify_index)
    assert setup_index < checksum_index < verify_index < create_index


def test_k3s_promotion_requires_cliproxy_digest_resolution() -> None:
    workflow = (ROOT / ".github/workflows/promote-k3s-images.yml").read_text(encoding="utf-8")
    assert "repository_dispatch:" in workflow
    assert "cliproxy-candidate-ready" in workflow
    assert "Resolve cliproxy candidate digest" in workflow
    assert "scripts/k3s/resolve_image_digest.py" in workflow
    assert "CLIPROXY_CANDIDATE_TAG" in workflow
    assert "cliproxy digest is required" in workflow
    assert 'ARGS+=(--cliproxy "${CLIPROXY}")' in workflow


def test_k3s_promotion_preserves_emergency_skip_deep_smoke() -> None:
    workflow = (ROOT / ".github/workflows/promote-k3s-images.yml").read_text(encoding="utf-8")
    assert "skip_deep_smoke=true" in workflow
    assert 'INPUT_SKIP}" == "true"' in workflow
    assert "needs.resolve-sha.outputs.skip_deep_smoke != 'true'" in workflow
    assert "Staging deep-smoke **skipped** via workflow_dispatch skip_deep_smoke=true" in workflow


def test_nightly_integration_installs_verified_compose_before_starting_stack() -> None:
    with (ROOT / ".github/workflows/nightly-integration.yml").open(encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)

    steps = workflow["jobs"]["real-provider-smoke"]["steps"]
    setup_index = next(
        index for index, step in enumerate(steps) if step.get("name") == "Install pinned Docker Compose v2"
    )
    setup_run = steps[setup_index]["run"]
    cleanup_index = next(index for index, step in enumerate(steps) if step.get("name") == "Stop services")
    cleanup = steps[cleanup_index]
    cleanup_run = cleanup["run"]

    assert "COMPOSE_VERSION=v2.27.0" in setup_run
    assert (
        "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-${COMPOSE_ARCH}"
        in setup_run
    )
    assert "f3ba3bf1e4ab18e96c2d36526a075a02a78fb5f8e80d3e3ca9c5bf256d81d0a0" in setup_run
    assert "37a1c197fef5fda2a3df2d5ae0d7762ad2a00e30946ad06d4ad9fa8cef16d9e7" in setup_run
    assert 'COMPOSE_DIR="${HOME}/.docker/cli-plugins"' in setup_run
    assert 'COMPOSE_BIN="${COMPOSE_DIR}/docker-compose"' in setup_run
    assert 'COMPOSE_TMP="$(mktemp "${COMPOSE_DIR}/docker-compose.XXXXXX")"' in setup_run
    assert "trap 'rm -f \"$COMPOSE_TMP\"' EXIT" in setup_run
    assert '--output "$COMPOSE_TMP"' in setup_run
    assert 'printf \'%s  %s\\n\' "$COMPOSE_SHA256" "$COMPOSE_TMP" | sha256sum --check --strict' in setup_run
    assert 'chmod +x "$COMPOSE_TMP"' in setup_run
    assert 'mv -f "$COMPOSE_TMP" "$COMPOSE_BIN"' in setup_run
    assert 'docker compose version --short | grep -Fx "${COMPOSE_VERSION#v}"' in setup_run
    assert 'echo "NIGHTLY_COMPOSE_READY=true" >> "$GITHUB_ENV"' in setup_run

    download_index = setup_run.index('--output "$COMPOSE_TMP"')
    verify_index = setup_run.index("sha256sum --check --strict")
    chmod_index = setup_run.index('chmod +x "$COMPOSE_TMP"')
    move_index = setup_run.index('mv -f "$COMPOSE_TMP" "$COMPOSE_BIN"')
    version_index = setup_run.index("docker compose version --short")
    ready_index = setup_run.index("NIGHTLY_COMPOSE_READY=true")
    assert download_index < verify_index < chmod_index < move_index < version_index < ready_index

    for index, step in enumerate(steps):
        run = step.get("run", "")
        if index != setup_index and ("docker compose" in run or "./dev-env.sh" in run):
            assert setup_index < index

    assert cleanup["if"] == "always()"
    assert 'if [[ "${NIGHTLY_COMPOSE_READY:-}" == "true" ]]; then' in cleanup_run
    assert "docker compose -f docker-compose.dev.yml -p aidev1 logs || true" in cleanup_run
    assert "Docker Compose setup did not complete; skipping logs and teardown." in cleanup_run
    ready_guard_index = cleanup_run.index("NIGHTLY_COMPOSE_READY:-")
    logs_index = cleanup_run.index("docker compose -f")
    stop_index = cleanup_run.index("./dev-env.sh stop 1")
    skip_index = cleanup_run.index("else\n")
    assert ready_guard_index < logs_index < stop_index < skip_index
    assert "./dev-env.sh stop 1" in cleanup_run
    assert "./dev-env.sh stop 1 || true" not in cleanup_run


def test_nightly_integration_provisions_runner_requirements_before_smoke() -> None:
    with (ROOT / ".github/workflows/nightly-integration.yml").open(encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)

    steps = workflow["jobs"]["real-provider-smoke"]["steps"]
    setup_index = next(
        index for index, step in enumerate(steps) if step.get("uses") == "./.github/actions/setup-python-venv"
    )
    setup_inputs = steps[setup_index]["with"]
    requirements = setup_inputs["requirements-files"]

    assert "requirements/ci-runner-venv.txt" in requirements
    assert "tests/integration/requirements.txt" in requirements
    path_index = next(index for index, step in enumerate(steps) if step.get("name") == "Add CI venv to PATH")
    path_run = steps[path_index]["run"]
    smoke_index = next(index for index, step in enumerate(steps) if "./dev-env.sh test 1" in step.get("run", ""))
    assert "$GITHUB_WORKSPACE/.venv-ci/bin" in path_run
    assert setup_index < path_index < smoke_index
