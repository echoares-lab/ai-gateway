import os
from pathlib import Path

def get_project_root() -> Path:
    """Detects repository root dynamically."""
    path = Path(__file__).resolve()
    for parent in path.parents:
        if (parent / ".git").exists() or (parent / "docker-compose.yml").exists():
            return parent
    return path.parents[2] # Fallback
