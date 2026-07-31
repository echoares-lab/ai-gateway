# Scripts layout

Operational and CI helpers are grouped by theme. Prefer these paths in docs,
Makefile targets, and workflows. Thin root wrappers remain for
`gen-client-config.sh` and `setup-repo-env.sh`.

| Directory | Purpose | Notable entrypoints |
|-----------|---------|---------------------|
| `scripts/ci/` | CI runner helpers | `ci-free-mock-host-ports.sh`, `ci-runner-status.sh`, `ci-runner-reregister.sh` |
| `scripts/ops/` | Day-2 ops, env, mock seed, client bootstrap | `docker-cleanup.sh`, `sync-env-to-op.sh`, `push-rotated-secrets-to-op.sh`, `generate-staging-configmap.sh`, `load-mock-data.sh`, `generate-litellm-mock-seed.sh`, `gen-client-config.sh`, `setup-repo-env.sh`, `verify-docker-naming.sh`, `validate_dev_env_slots.py`, `validate_exception_inventory.py`, `validate_config_promotion.py` |
| `scripts/policy/` | Policy profile validate/promote + cheap drift | `validate_policy_profiles.py`, `promote_policy_profiles.py`, `cheap_drift_check.py` |
| `scripts/cliproxy/` | CLIProxy probe/sync tooling | `sync_models_probe_classify.py`, `track_probe_failures.py`, `pool_sync.py`, `sync-cliproxy-pool-priority.sh` |
| `scripts/k3s/` | Staging/prod image pin promotion | `promote_k3s_images.py` |

Root wrappers:

```bash
./gen-client-config.sh …   # → scripts/ops/gen-client-config.sh
./setup-repo-env.sh …      # → scripts/ops/setup-repo-env.sh
```

Common Make targets still call the themed paths:

```bash
make validate-policy-profiles   # scripts/policy/validate_policy_profiles.py
make drift-cheap                # scripts/policy/cheap_drift_check.py
make validate-dev-env-slots     # scripts/ops/validate_dev_env_slots.py
make validate-exception-inventory # scripts/ops/validate_exception_inventory.py
make validate-config-promotion   # scripts/ops/validate_config_promotion.py
```
