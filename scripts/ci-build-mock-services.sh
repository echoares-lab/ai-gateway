#!/usr/bin/env bash
# Build mock-stack images with Buildx cache when path filters say rebuild, or when
# the tagged image is missing locally (first run / runner reboot).
set -euo pipefail

build_if_needed() {
  local changed="$1" image="$2" context="$3" scope="$4"
  if [[ "$changed" != "true" ]] && docker image inspect "$image" >/dev/null 2>&1; then
    echo "Skipping $image (unchanged, image present locally)"
    return 0
  fi
  echo "Building $image from $context (scope=$scope)"
  docker buildx build \
    --load \
    --tag "$image" \
    --build-arg GIT_SHA="${GIT_SHA:-unknown}" \
    --build-arg ENVIRONMENT="${ENVIRONMENT:-ci}" \
    --cache-from "type=gha,scope=${scope}" \
    --cache-from "type=local,src=/var/cache/ai-gateway/buildkit" \
    --cache-to "type=gha,mode=max,scope=${scope}" \
    --cache-to "type=local,dest=/var/cache/ai-gateway/buildkit,mode=max" \
    "$context"
}

build_if_needed "${BUILD_CLIPROXY:-false}" "ai-mock-upstream:latest" "./tests/mock-upstream" "cliproxy-mock"
build_if_needed "${BUILD_POLICY:-false}" "ai-mock-policy-engine:latest" "./tests/mock-policy-engine" "policy-engine-mock"
