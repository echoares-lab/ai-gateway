# Model Management Investigation

## Overview
The current model management workflow in `cliproxy-setup.sh sync-models` relies on directly parsing and modifying `litellm-config.yaml` using regex and shell scripts. This is fragile and prone to conflicts, especially as the number of models and metadata (costs, fallbacks) grows.

## Conflicting Patterns / Issues
1. **Regex Brittleness:** The `sed` and `grep` based parsing of YAML in `cliproxy-setup.sh` is inherently risky. Changes in YAML formatting (whitespace, comment placement) can cause parsing failures or incorrect modifications.
2. **Concurrent Mutation:** If `sync-models` is run while another process or user is editing `litellm-config.yaml`, the file state can be corrupted.
3. **Implicit Dependencies:** Fallbacks and model-info depend on the order and existence of `model_name` blocks, which are auto-generated. This creates a tight, fragile coupling between the sync script and the config file structure.
4. **Visibility/Management:** Because models are "just lines in a YAML", there is no clear hierarchy, tiering, or model-family management. Managing new families requires updating the logic inside `cliproxy-setup.sh` itself.

## Options for Improvement

### Option 1: API-Driven Model Management (Recommended)
Instead of treating `litellm-config.yaml` as the source of truth, treat the LiteLLM/CLIProxy system as a registry.
* **Mechanism:** Add a thin management service or extend the existing `translator` to handle model CRUD via API.
* **Benefits:** Atomic updates, validation of new models *before* they touch configuration, structured metadata storage.
* **Implementation:** The `sync-models` script would call an API `GET /models/sync` to get the desired state, then update the config file in one atomic operation (or update a dynamic `models.json` file that LiteLLM includes).

### Option 2: Config-as-Code / Modular YAML
Break `litellm-config.yaml` into smaller, includeable files (e.g., `models.d/gemini.yaml`, `models.d/claude.yaml`).
* **Mechanism:** Use LiteLLM's ability to support modular config files.
* **Benefits:** Reduces scope of conflict to specific provider files, allows for easier manual overrides without risking the whole config.

### Option 3: Improved Metadata / Tier Management
Regardless of the storage mechanism (API or file), the system needs a more robust way to define model tiers (Flash, Pro, OSS).
* **Proposed Architecture:**
    * **Model Definition Schema:** Define a JSON schema for a "model bundle" that includes:
        * `family`: e.g., `gemini-3`
        * `tier`: e.g., `pro`, `flash`
        * `capabilities`: e.g., `vision`, `reasoning`
        * `fallbacks`: A list of model aliases *within the same hierarchy*.
    * **Dynamic Config Injection:** Generate the final `litellm-config.yaml` dynamically from these "bundles" using a template engine (like Jinja2), rather than regex-munging the final file.

## Strategic Recommendations
1. **Move to Template-Based Generation:** Stop using `sed`/`grep` on the production YAML. Use a Python script that reads a `models.json` or YAML-based definition and generates the *entire* `litellm-config.yaml`.
2. **Implement an API for Health/Sync:** Shift the "what models are alive" check to a service that maintains a cached registry, so the `sync-models` script becomes a thin client that triggers a re-render of the configuration.
3. **Tiered Management:** Implement a grouping system where a new model automatically inherits capabilities and fallback targets based on its defined family and tier.
