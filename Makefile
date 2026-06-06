.PHONY: lint test-unit test-mock test-fast test-e2e validate-policy-profiles test-sync-models-probe

# Lint the translator + the mock upstream app (mirrors the CI fast tier).
lint:
	ruff check services/translator/main.py tests/mock-upstream/app.py
	ruff format --check services/translator/main.py tests/mock-upstream/app.py

# Regression tests for sync-models probe classification (429 must preserve catalog).
test-sync-models-probe:
	python3 -m pytest tests/test_sync_models_probe_classify.py -v
	bash tests/test-sync-models-probe.sh

# Unit tests: build the translator image and run the fully-mocked suite (parallel, CI parity).
test-unit:
	docker build -t ai-translator-test:latest services/translator
	docker run --rm ai-translator-test:latest sh -c 'pytest test_translator*.py -n auto -v'
	python3 -m venv .venv-policy-engine 2>/dev/null || python3 -m venv .venv-policy-engine
	.venv-policy-engine/bin/pip install -q -r services/policy-engine/requirements.txt -r services/policy-engine/requirements-test.txt
	PYTHONPATH=services/policy-engine .venv-policy-engine/bin/pytest services/policy-engine/test_*.py -v

# Mock tier: translator + litellm + canned upstream (slot 9 -> :4090), no OAuth.
# Tears the stack down afterward even if tests fail.
test-mock:
	./dev-env.sh start-mock 9
	@for i in $$(seq 1 30); do curl -sf http://localhost:4090/health >/dev/null && break; sleep 2; done
	-./dev-env.sh test-mock 9
	./dev-env.sh stop-mock 9

# Offline schema check for git-tracked policy profile promotion (P0-7).
validate-policy-profiles:
	python3 scripts/validate_policy_profiles.py

# Fast tier = Gate A + B locally (no OAuth, no real LLM).
# Note: multi-repo-isolation is CI path-filtered only — run manually when touching dev-env.sh / cliproxy-setup.sh:
#   bash tests/test-multi-repo-isolation.sh
test-fast: lint test-unit validate-policy-profiles test-sync-models-probe test-mock

# Full real-provider E2E. Needs real OAuth in ~/.cli-proxy-api (slot 1 -> :4010).
# Runs only the slim `smoke` subset.
test-e2e:
	./dev-env.sh start 1
	@for i in $$(seq 1 30); do curl -sf http://localhost:4010/health >/dev/null && break; sleep 3; done
	-./dev-env.sh test 1 -- -m "integration and smoke"
	./dev-env.sh stop 1
