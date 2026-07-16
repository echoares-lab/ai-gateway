"""Build-provided release identity for runtime diagnostics."""

from __future__ import annotations

import os


def release_metadata() -> dict[str, str]:
    """Return human and immutable release identifiers without runtime Git access."""
    version = os.getenv("APP_VERSION", "0.0.0-dev")
    git_sha = os.getenv("GIT_SHA", "unknown")
    short_sha = git_sha[:7] if git_sha != "unknown" else "unknown"
    return {
        "version": version,
        "git_sha": git_sha,
        "display_version": f"{version}+sha.{short_sha}",
    }
