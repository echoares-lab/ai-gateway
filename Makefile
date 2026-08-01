.PHONY: lint test-unit test-mock test-fast test-e2e test-scripts validate-policy-profiles validate-production-secrets validate-admin-exposure validate-litellm-config-drift validate-dev-env-slots validate-exception-inventory validate-config-promotion promote-config-artifact test-sync-models-probe test-compose-config test-dev-env drift-cheap clean-db

CONTAINER_PREFIX ?= PROD-
MOCK_TEST_ARGS ?=

# Cleans up Docker volumes for a fresh database state.
clean-db:
	docker volume rm ai_langfuse_postgres_data || true
	docker volume prune -f


# Lint the gateway-engine and credential-prober (mirrors the CI fast tier).
lint:
	ruff check services/gateway-engine/ services/credential-prober/ scripts/
	ruff format --check services/gateway-engine/ services/credential-prober/ scripts/

# Regression tests for sync-models probe classification (429 must preserve catalog).
test-sync-models-probe:
	python3 -m pytest tests/test_sync_models_probe_classify.py -v
	bash tests/test-sync-models-probe.sh

test-dev-env:
	bash tests/test-dev-env.sh

test-scripts:
	bash tests/test-quota-summary.sh

test-compose-config:
	python3 -m pytest tests/test_litellm_compose_migration.py -v
	docker compose -f docker-compose.yml config >/dev/null
	@if grep -q 'cli-proxy-api:latest' docker-compose.yml; then \
	  echo 'ERROR: docker-compose.yml must not default CLIPROXY_IMAGE to :latest' >&2; exit 1; \
	fi
	@if grep -n 'command:.*uvicorn.*--reload' docker-compose.yml >/dev/null; then \
	  echo 'ERROR: gateway-engine must not use uvicorn --reload in docker-compose.yml' >&2; exit 1; \
	fi
	@if grep -nE './services/gateway-engine:/app' docker-compose.yml >/dev/null; then \
	  echo 'ERROR: gateway-engine must not bind-mount ./services/gateway-engine:/app in docker-compose.yml' >&2; exit 1; \
	fi

# Unit tests: build the gateway-engine image and run the fully-mocked suite (parallel, CI parity).
test-unit:
	docker build -t ai-gateway-engine-test:latest services/gateway-engine
	docker run --rm --name $(CONTAINER_PREFIX)ai-gateway-engine-test ai-gateway-engine-test:latest sh -c 'pytest test_gateway_engine*.py -n auto -v'

# Mock tier: in-memory ASGI integration tests (no OAuth, canned upstream).
test-mock:
	python3 -m pytest tests/integration/ -m mock -v $(MOCK_TEST_ARGS)

# Offline schema check for git-tracked policy profile promotion (P0-7).
validate-policy-profiles:
	python3 scripts/policy/validate_policy_profiles.py

# Contract tests for required production backing-service secrets. These tests
# use synthetic values and never load or print real credentials.
validate-production-secrets:
	python3 -m pytest tests/test_production_secrets.py -v

# Ensure every administrative/operational route has an explicit exposure class.
validate-admin-exposure:
	python3 scripts/ops/validate_admin_exposure.py

# Compare sanitized LiteLLM YAML and Postgres metadata fixtures; no credentials
# or live database access are used.
validate-litellm-config-drift:
	python3 scripts/ops/validate_litellm_config_drift.py tests/fixtures/litellm_config_drift/clean.yaml tests/fixtures/litellm_config_drift/clean-db.json
	python3 -m pytest tests/test_litellm_config_drift.py -v

# Side-effect-free slot/project collision preflight over sanitized metadata.
validate-dev-env-slots:
	python3 scripts/ops/validate_dev_env_slots.py tests/fixtures/dev_env_slots/clean.json
	python3 -m pytest tests/test_dev_env_slot_preflight.py -v

# Emit the exhaustive broad-exception source/line inventory and enforce rules.
validate-exception-inventory:
	python3 scripts/ops/validate_exception_inventory.py
	python3 -m pytest tests/test_exception_inventory.py tests/test_exception_narrowing.py -v

# Validate sanitized staging-to-production config artifact metadata.
validate-config-promotion:
	python3 scripts/ops/validate_config_promotion.py tests/fixtures/config_promotion/clean.json --target production
	python3 -m pytest tests/test_config_promotion_contract.py -v

# Enforce the promotion contract and emit a sanitized audit record.
promote-config-artifact:
	python3 -m pytest tests/test_config_promotion_gate.py -v

# Cheap drift detector: set-membership only, no completion probes.
drift-cheap:
	python3 scripts/policy/cheap_drift_check.py --litellm-config tests/fixtures/cheap_drift/litellm-config.yaml --model-registry tests/fixtures/cheap_drift/model-registry.yaml --catalog-file tests/fixtures/cheap_drift/catalog-no-drift.json

# Fast tier = Gate A + B locally (no OAuth, no real LLM).
# Note: multi-repo-isolation is CI path-filtered only — run manually when touching dev-env.sh / cliproxy-setup.sh:
#   bash tests/test-multi-repo-isolation.sh
test-fast: lint test-unit validate-policy-profiles validate-production-secrets validate-admin-exposure validate-litellm-config-drift validate-dev-env-slots validate-exception-inventory validate-config-promotion drift-cheap test-sync-models-probe test-compose-config test-mock

# Full real-provider E2E. Needs real OAuth in ~/.cli-proxy-api (slot 1 -> :4010).
# Runs only the slim `smoke` subset.
test-e2e: clean-db
	./dev-env.sh start 1
	@for i in $$(seq 1 30); do curl -sf http://localhost:4010/health >/dev/null && break; sleep 3; done
	-./dev-env.sh test 1 -- -m "integration and smoke"
	./dev-env.sh stop 1
