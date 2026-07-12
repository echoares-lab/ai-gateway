#!/usr/bin/env bash
# Thin wrapper — canonical script lives under scripts/ops/
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/ops/gen-client-config.sh" "$@"
