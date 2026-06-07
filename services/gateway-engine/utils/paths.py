import os
from pathlib import Path

def get_project_root() -> Path:
    """
    Dynamically detects the repository root by looking for '.git' or 'docker-compose.yml'
    in parent directories.
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() or (parent / "docker-compose.yml").exists():
            return parent
    # Fallback to the directory containing 'services' if not found
    for parent in current.parents:
        if (parent / "services").exists():
            return parent
    # Last resort: return the parent of 'services/gateway-engine'
    return Path(__file__).resolve().parents[2]
