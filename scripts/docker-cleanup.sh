#!/usr/bin/env bash

# docker-cleanup.sh
# Cleans up Docker containers associated with this project.
# Usage: ./scripts/docker-cleanup.sh [--testing-only]

set -e

# Identify containers by project label or name prefix if possible.
# Since we don't have explicit project labels for all, we'll target based on name or known patterns.
# For now, let's target containers with a name related to this repo.
# In the future, we could use project labels if added to docker-compose.

cleanup_pattern="TESTING-|PROD-"

if [[ "$1" == "--testing-only" ]]; then
    cleanup_pattern="TESTING-"
fi

echo "Cleaning up containers matching: $cleanup_pattern"

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
