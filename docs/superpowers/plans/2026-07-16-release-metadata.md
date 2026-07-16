# Release Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish Gateway Engine release `1.2.1` with immutable source identity and expose the combined `1.2.1+sha.<short-sha>` value consistently through HTTP, OCI metadata, and Kubernetes metadata.

**Architecture:** A repository-root `VERSION` file is the human SemVer source. CI injects that version, the full commit SHA, and build time into the Gateway Engine image; a small release-metadata module reads the injected environment and supplies `GET /version`. The promotion script keeps the immutable image SHA/digest pin and independently updates the Kubernetes version label in the external k3s-01 overlay.

**Tech Stack:** Python 3.12, FastAPI, pytest, Docker/OCI labels, GitHub Actions, Kustomize YAML.

## Global Constraints

- Human version is `1.2.1` and image SemVer tags come from the root `VERSION` file.
- Immutable full Git SHA and deployed image digest/SHA tag remain the deployment and rollback identity.
- `display_version` is `<semver>+sha.<first-7-sha>`.
- Local builds fall back to `0.0.0-dev` and `unknown` without querying Git at runtime.
- The new endpoint must be registered in `docs/openapi/gateway-engine.yaml`.
- Authoritative Kubernetes files change only in `echoares-lab/k3s-01` issue #46 and its isolated worktree.

---

### Task 1: Gateway Engine release contract

**Files:**
- Create: `VERSION`
- Create: `services/gateway-engine/core/release_metadata.py`
- Create: `services/gateway-engine/test_gateway_engine_release_metadata.py`
- Modify: `services/gateway-engine/main.py`
- Modify: `docs/openapi/gateway-engine.yaml`

**Interfaces:**
- Produces: `release_metadata() -> dict[str, str]` with exactly `version`, `git_sha`, and `display_version`.
- Produces: unauthenticated `GET /version` returning that dictionary.

- [ ] **Step 1: Write failing metadata tests**

```python
def test_release_metadata_uses_injected_version_and_full_sha(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.2.1")
    monkeypatch.setenv("GIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    assert release_metadata() == {
        "version": "1.2.1",
        "git_sha": "0123456789abcdef0123456789abcdef01234567",
        "display_version": "1.2.1+sha.0123456",
    }
```

- [ ] **Step 2: Verify the test fails because the module is absent**

Run: `cd services/gateway-engine && pytest test_gateway_engine_release_metadata.py -v`

- [ ] **Step 3: Implement environment-backed metadata and local fallbacks**

```python
def release_metadata() -> dict[str, str]:
    version = os.getenv("APP_VERSION", "0.0.0-dev")
    git_sha = os.getenv("GIT_SHA", "unknown")
    short_sha = git_sha[:7] if git_sha != "unknown" else "unknown"
    return {"version": version, "git_sha": git_sha, "display_version": f"{version}+sha.{short_sha}"}
```

- [ ] **Step 4: Add a failing HTTP test, then expose `GET /version` and document its exact schema/example**

Run: `cd services/gateway-engine && pytest test_gateway_engine_release_metadata.py -v`

- [ ] **Step 5: Commit the green API unit**

```bash
git add VERSION services/gateway-engine/core/release_metadata.py services/gateway-engine/test_gateway_engine_release_metadata.py services/gateway-engine/main.py docs/openapi/gateway-engine.yaml
git commit -m "feat(gateway-engine): expose release metadata"
```

### Task 2: OCI build and publication metadata

**Files:**
- Modify: `services/gateway-engine/Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.dev.yml`
- Modify: `.github/workflows/ci.yml`
- Create: `tests/test_release_metadata_contract.py`

**Interfaces:**
- Consumes: root `VERSION`, full `GIT_SHA`, and ISO-8601 `BUILD_DATE`.
- Produces: image environment `APP_VERSION`/`GIT_SHA`; OCI version, revision, source, and created labels; full-SHA, SemVer, and compatibility `latest` tags.

- [ ] **Step 1: Write failing static contract tests for Dockerfile and CI metadata**

```python
def test_gateway_image_declares_release_metadata():
    dockerfile = Path("services/gateway-engine/Dockerfile").read_text()
    assert "ARG APP_VERSION=0.0.0-dev" in dockerfile
    assert "org.opencontainers.image.version=$APP_VERSION" in dockerfile
```

- [ ] **Step 2: Verify contract tests fail on missing version/build-date metadata**

Run: `pytest tests/test_release_metadata_contract.py -v`

- [ ] **Step 3: Add build args, OCI labels, runtime environment, and CI-derived full SHA/SemVer/build date**

CI must read `VERSION`, validate `^[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$`, and tag the pushed Gateway Engine image with the full SHA, `1.2.1`, and `latest`.

- [ ] **Step 4: Run contract tests and inspect a local image**

Run: `pytest tests/test_release_metadata_contract.py -v`

Run: `docker build --build-arg APP_VERSION=1.2.1 --build-arg GIT_SHA=0123456789abcdef0123456789abcdef01234567 --build-arg BUILD_DATE=2026-07-16T00:00:00Z -t gateway-release-test services/gateway-engine`

Run: `docker inspect gateway-release-test`

- [ ] **Step 5: Commit the green image-publication unit**

```bash
git add services/gateway-engine/Dockerfile docker-compose.yml docker-compose.dev.yml .github/workflows/ci.yml tests/test_release_metadata_contract.py
git commit -m "feat(release): publish versioned gateway images"
```

### Task 3: Version-aware Kubernetes promotion

**Files:**
- Modify: `scripts/k3s/promote_k3s_images.py`
- Modify: `tests/test_promote_k3s_images.py`
- Modify: `.github/workflows/promote-k3s-images.yml`
- Modify: `docs/CICD_PHASE2_CD_K3S.md`
- Modify: `docs/CICD_PHASE2_STAGING.md`

**Interfaces:**
- Consumes: `--gateway-engine <full-sha-or-digest>` and `--gateway-version 1.2.1`.
- Produces: one k3s-01 kustomization diff containing both the immutable image pin and `app.kubernetes.io/version` label.

- [ ] **Step 1: Extend tests first to require version-label replacement and reject invalid label values**

```python
out = _set_gateway_version(FIXTURE, "1.2.1")
assert "app.kubernetes.io/version: 1.2.1" in out
```

- [ ] **Step 2: Verify the focused promotion tests fail**

Run: `PYTHONPATH=. pytest tests/test_promote_k3s_images.py -v`

- [ ] **Step 3: Implement `--gateway-version`, workflow propagation from `VERSION`, full-SHA promotion, and GitOps PR reporting**

The script changes only the Gateway Engine version label. It must not put the version in selectors and must not replace an immutable image pin with a SemVer tag.

- [ ] **Step 4: Run promotion and workflow contract tests**

Run: `PYTHONPATH=. pytest tests/test_promote_k3s_images.py tests/test_release_metadata_contract.py -v`

- [ ] **Step 5: Commit the green promotion unit**

```bash
git add scripts/k3s/promote_k3s_images.py tests/test_promote_k3s_images.py .github/workflows/promote-k3s-images.yml docs/CICD_PHASE2_CD_K3S.md docs/CICD_PHASE2_STAGING.md
git commit -m "feat(k3s): promote gateway version metadata"
```

### Task 4: External k3s-01 manifest foundation

**Files:**
- Modify in `/home/dev/worktrees/k3s-01-ai-gateway-release-version`: `kubernetes/workloads/home/ai-gateway/overlays/k3s-01/kustomization.yaml`

**Interfaces:**
- Produces: `labels` entry targeting Deployment metadata and pod templates, which the ai-gateway promotion script updates.

- [ ] **Step 1: Render the current overlay and confirm the Gateway Engine lacks the version label**

Run: `kubectl kustomize kubernetes/workloads/home/ai-gateway/overlays/k3s-01 | rg -n "app.kubernetes.io/version"`

- [ ] **Step 2: Add a Kustomize label transformer entry with `includeSelectors: false` and `includeTemplates: true`**

```yaml
labels:
  - pairs:
      app.kubernetes.io/version: 1.2.1
    includeSelectors: false
    includeTemplates: true
```

- [ ] **Step 3: Render and verify Deployment/pod labels while selectors remain unchanged**

Run: `kubectl kustomize kubernetes/workloads/home/ai-gateway/overlays/k3s-01 >/tmp/ai-gateway-rendered.yaml`

- [ ] **Step 4: Commit, push, and open a draft k3s-01 PR linked to issue #46**

```bash
git add kubernetes/workloads/home/ai-gateway/overlays/k3s-01/kustomization.yaml
git commit -m "feat(ai-gateway): label release version"
```

### Task 5: Full verification and publication

**Files:** No new files.

- [ ] **Step 1: Run Gate A and Gate B**

Run: `make test-fast`

- [ ] **Step 2: Validate Docker Compose and the release image labels**

Run: `docker compose -f docker-compose.yml config >/dev/null && docker compose -f docker-compose.dev.yml config >/dev/null`

- [ ] **Step 3: Verify both repository diffs against their issues and run `git diff --check`**

- [ ] **Step 4: Push `feat/release-metadata`, open a draft PR linked to #379, and leave both worktrees available for review fixes**

- [ ] **Step 5: Do not merge until required CI is green; record any external GitOps dependency in both PRs**
