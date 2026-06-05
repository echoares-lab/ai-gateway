.PHONY: lint test-unit test-mock test-fast test-e2e validate-policy-profiles

# Lint the translator + the mock upstream app (mirrors the CI fast tier).
lint:
	ruff check services/translator/translator.py tests/mock-upstream/app.py
	ruff format --check services/translator/translator.py tests/mock-upstream/app.py

# Unit tests: build the translator image and run the fully-mocked suite.
test-unit:
	docker build -t ai-translator-test:latest services/translator
	docker run --rm ai-translator-test:latest sh -c 'pytest test_translator*.py -v'

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

# Fast tier = what CI runs on every push/PR (no OAuth, no real LLM).
test-fast: lint test-unit validate-policy-profiles test-mock

# Full real-provider E2E. Needs real OAuth in ~/.cli-proxy-api (slot 1 -> :4010).
# Runs only the slim `smoke` subset.
test-e2e:
	./dev-env.sh start 1
	@for i in $$(seq 1 30); do curl -sf http://localhost:4010/health >/dev/null && break; sleep 3; done
	-./dev-env.sh test 1 -- -m "integration and smoke"
	./dev-env.sh stop 1
