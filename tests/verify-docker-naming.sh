#!/usr/bin/env bash
# verify-docker-naming.sh
# Verifies that containers have the expected PROD- or TESTING- prefixes.

set -e

echo "--- Verifying PROD- containers (from docker-compose.yml) ---"
# Launch PROD stack
docker compose -f docker-compose.yml up -d
sleep 5 # Allow time for containers to start

# Check PROD containers
running_prod=$(docker ps --format "{{.Names}}" | grep "^PROD-" || true)
echo "Found PROD containers:"
echo "$running_prod"

# Assert that some PROD containers exist
if [ -z "$running_prod" ]; then
    echo "ERROR: No containers with PROD- prefix found!"
    exit 1
fi

echo "--- Verifying TESTING- containers (from docker-compose.dev.yml) ---"
# Launch TESTING stack (using a specific project name to avoid conflict)
docker compose -f docker-compose.dev.yml -p test-dev-stack up -d
sleep 5

# Check TESTING containers
running_test=$(docker ps --format "{{.Names}}" | grep "^TESTING-" || true)
echo "Found TESTING containers:"
echo "$running_test"

# Assert that some TESTING containers exist
if [ -z "$running_test" ]; then
    echo "ERROR: No containers with TESTING- prefix found!"
    exit 1
fi

echo "--- Running cleanup script ---"
./scripts/docker-cleanup.sh

echo "--- Verifying cleanup ---"
remaining=$(docker ps -a --format "{{.Names}}" | grep -E "^(PROD-|TESTING-)" || true)

if [ -n "$remaining" ]; then
    echo "ERROR: Cleanup failed! Remaining containers:"
    echo "$remaining"
    exit 1
else
    echo "Cleanup successful. No containers with PROD- or TESTING- prefixes found."
fi

# Bring down remaining dev stack
docker compose -f docker-compose.dev.yml -p test-dev-stack down -v
# Bring down remaining prod stack
docker compose -f docker-compose.yml down -v

echo "Verification complete and successful."
