#!/usr/bin/env bash

# docker-cleanup.sh
# Cleans up Docker containers associated with this project.
# Usage: ./scripts/docker-cleanup.sh [--testing-only | --all | --check-non-standard]

set -e

cleanup_pattern="TESTING-|PROD-"
mode="standard"

if [[ "$1" == "--testing-only" ]]; then
    cleanup_pattern="TESTING-"
elif [[ "$1" == "--all" ]]; then
    cleanup_pattern="."
    mode="all"
elif [[ "$1" == "--check-non-standard" ]]; then
    echo "Checking for non-standard containers (not PROD- or TESTING-)..."
    docker ps -a --format "{{.Names}}" | grep -vE "^(PROD-|TESTING-)"
    exit 0
fi

echo "Cleaning up containers matching: $cleanup_pattern ($mode mode)"

# List containers matching the pattern
containers=$(docker ps -a --format "{{.Names}}" | grep -E "$cleanup_pattern" || true)

if [ -z "$containers" ]; then
    echo "No containers found to clean."
    exit 0
fi

echo "Found containers:"
echo "$containers"

# Stop and remove containers
for container in $containers; do
    echo "Stopping and removing container: $container"
    docker stop "$container" >/dev/null 2>&1 || true
    docker rm "$container" >/dev/null 2>&1 || true
done

echo "Cleanup complete."
