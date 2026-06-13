.PHONY: lint test-unit test-mock test-fast test-e2e validate-policy-profiles test-sync-models-probe test-dev-env clean-db

CONTAINER_PREFIX ?= PROD-

# Cleans up Docker volumes for a fresh database state.
clean-db:
	docker volume rm ai_langfuse_postgres_data || true
	docker volume prune -f


# Lint the gateway-engine (mirrors the CI fast tier).
lint:
	ruff check services/gateway-engine/main.py
	ruff format --check services/gateway-engine/main.py

# Regression tests for sync-models probe classification (429 must preserve catalog).
test-sync-models-probe:
	python3 -m pytest tests/test_sync_models_probe_classify.py -v
	bash tests/test-sync-models-probe.sh

test-dev-env:
	bash tests/test-dev-env.sh

# Unit tests: build the gateway-engine image and run the fully-mocked suite (parallel, CI parity).
test-unit:
	docker build -t ai-gateway-engine-test:latest services/gateway-engine
	docker run --rm --name $(CONTAINER_PREFIX)ai-gateway-engine-test ai-gateway-engine-test:latest sh -c 'pytest test_gateway_engine*.py -n auto -v'

# Mock tier: in-memory ASGI integration tests (no OAuth, canned upstream).
test-mock: clean-db
	python3 -m pytest tests/integration/ -m mock -v

# Offline schema check for git-tracked policy profile promotion (P0-7).
validate-policy-profiles:
	python3 scripts/validate_policy_profiles.py

# Fast tier = Gate A + B locally (no OAuth, no real LLM).
# Note: multi-repo-isolation is CI path-filtered only — run manually when touching dev-env.sh / cliproxy-setup.sh:
#   bash tests/test-multi-repo-isolation.sh
test-fast: lint test-unit validate-policy-profiles test-sync-models-probe test-mock

# Full real-provider E2E. Needs real OAuth in ~/.cli-proxy-api (slot 1 -> :4010).
# Runs only the slim `smoke` subset.
test-e2e: clean-db
	./dev-env.sh start 1
	@for i in $$(seq 1 30); do curl -sf http://localhost:4010/health >/dev/null && break; sleep 3; done
	-./dev-env.sh test 1 -- -m "integration and smoke"
	./dev-env.sh stop 1
