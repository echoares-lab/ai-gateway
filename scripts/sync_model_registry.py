#!/usr/bin/env python3
import sys
import yaml
import os
from pathlib import Path

# Add services/gateway-engine to sys.path
# We assume the script is in scripts/ and the root is one level up.
root_dir = Path(__file__).resolve().parents[1]
sys.path.append(str(root_dir / "services" / "gateway-engine"))

try:
    from core.model_registry import ModelRegistryStore, ModelRegistryRecord
    from utils.paths import get_project_root
except ImportError as e:
    print(f"Import error: {e}")
    print(f"sys.path: {sys.path}")
    sys.exit(1)

def sync():
    root = get_project_root()
    yaml_path = root / "config" / "model-registry.yaml"
    
    if not yaml_path.exists():
        print(f"Error: {yaml_path} not found")
        sys.exit(1)
        
    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)
        
    models_data = data.get("models", [])
    models = []
    all_aliases = []
    
    for m in models_data:
        # Extract aliases if they are embedded in the model entry for convenience
        aliases = m.get("aliases", [])
        record = ModelRegistryRecord(**m)
        models.append(record)
        
        for alias in aliases:
            if "model_id" not in alias:
                alias["model_id"] = record.model_id
            if "provider" not in alias:
                alias["provider"] = record.provider
            all_aliases.append(alias)
            
    # Also check for a top-level aliases list in YAML
    top_level_aliases = data.get("aliases", [])
    all_aliases.extend(top_level_aliases)
    
    store = ModelRegistryStore()
    if not store.enabled:
        print("Error: Model registry database not configured (check DATABASE_URL or MODEL_REGISTRY_DATABASE_URL)")
        sys.exit(1)
        
    model_count = store.upsert_models(models)
    alias_count = store.upsert_aliases(all_aliases)
    
    print(f"Successfully synced {model_count} models and {alias_count} aliases to the database.")

if __name__ == "__main__":
    sync()
