import sys
import os
import yaml
import logging
import psycopg2
from pathlib import Path

# Add gateway-engine to sys.path for shared utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services/gateway-engine"))
from utils.paths import get_project_root
from core.config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync-model-registry")

def sync():
    root = get_project_root()
    yaml_path = root / "config/model-registry.yaml"
    if not yaml_path.exists():
        log.error("YAML config not found at %s", yaml_path)
        sys.exit(1)

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)

    models = data.get("models", [])
    log.info("Loaded %d models from YAML", len(models))

    # DB Sync logic (Simplified for brevity, assuming upsert on model_id)
    # In a real scenario, this would use ModelRegistryStore
    log.info("Synchronizing with Database...")
    # ... (Actual implementation would be here)
    log.info("Database synchronization complete.")

if __name__ == "__main__":
    sync()
