# Self-Hosted CI Runner Guide

AI Gateway CI runs on a **self-hosted runner group** (multiple physical hosts in the dev pool) with persistent disk on each machine. Behavior differs from GitHub-hosted runners: caches survive between jobs, host ports are fixed per machine, and workspace pre-clean is targeted (not full wipe).

See [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) and [`TESTING.md`](TESTING.md).

---

## Runner prerequisites

Install once on the runner image (or bake into AMI):

```bash
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3-venv docker.io docker-buildx-plugin direnv psmisc
sudo usermod -aG docker "$USER"
```

Ensure Docker Buildx is available (`docker buildx version`).

---

## Persistent cache directories

Create on the runner host (survives workspace pre-clean):

```bash
sudo mkdir -p /var/cache/ai-gateway/{pip,buildkit}
sudo chown -R "$(whoami):$(whoami)" /var/cache/ai-gateway
```

| Path | Purpose |
|------|---------|
| `/var/cache/ai-gateway/pip` | Optional pip wheel cache mirror |
| `/var/cache/ai-gateway/buildkit` | Docker BuildKit `type=local` layer cache |

CI uses **GitHub Actions cache** (`type=gha`) for Docker layers plus optional local cache on self-hosted.

The composite action [`.github/actions/setup-python-venv`](../.github/actions/setup-python-venv/action.yml) caches `~/.cache/pip` and `.venv-ci` keyed on requirements files.

Docker builds use [`.github/actions/build-docker-cached`](../.github/actions/build-docker-cached/action.yml) with scoped GHA cache (primarily `gateway-engine`). Gate B mock integration is in-memory (`make test-mock` / `pytest tests/integration/ -m mock`) — there is no mock compose image build step.

---

## Concurrency and ports

### What runs in parallel

| Layer | Group key | Effect |
|-------|-----------|--------|
| Workflow | `ci-CI Suite-<PR number or ref>` | Different PRs (and `main` pushes) run CI concurrently across the dev runner group |
| Fast jobs | (none) | `lint-and-syntax`, `unit-tests` (image build is inside this job), path-filtered jobs fan out to any idle runner |
| Docker jobs | `ci-docker-host-ports` | One mock or Gate C stack at a time globally (port collision guard; `runner.name` is not allowed in job concurrency groups) |

Workflow concurrency is **per ref**: a new push to the same PR cancels the in-progress run for that PR only. Other PRs are unaffected.

### What stays serialized

| Constraint | Reason |
|------------|--------|
| Job concurrency for Docker-heavy steps | Gate C (`real-provider-e2e`) uses fixed host ports (e.g. 4010/4011) |
| Stable stack `:4000` | Must not collide with a Gate C stack on the same host |

Fast jobs and in-memory Gate B can fan out; only one Gate C Docker stack should bind host ports at a time.

---

## Port / volume cleanup helpers

Gate B no longer starts a mock Docker stack. `CI_MOCK_FRESH_DB` / `CI_MOCK_DOWN_VOLUMES` and `scripts/ci/ci-free-mock-host-ports.sh` remain for Gate C / legacy host-port cleanup when a real-provider stack was left running.

---

## Workspace pre-clean

Jobs use inline pre-clean **before** `actions/checkout` (local composite actions are unavailable until the repo is checked out). The clean removes checkout contents only — it preserves `/var/cache/ai-gateway`:

1. Fix ownership on `$GITHUB_WORKSPACE`
2. Remove prior checkout files (not cache dirs)
3. Ensure `/var/cache/ai-gateway/{pip,buildkit}` exists

See [`.github/actions/pre-clean-self-hosted`](../.github/actions/pre-clean-self-hosted/action.yml) for the canonical script (reference for runner setup docs).

---

## Job dependency graph (fast-fail)

```
changes ─┬─► lint-and-syntax ──┬─► mock-integration (in-memory Gate B)
         │                     └─► real-provider-e2e (opt-in Gate C)
         ├─► unit-tests (builds gateway-engine image)
         ├─► credential-prober (path-filtered)
         └─► multi-repo-isolation (path-filtered)
```

`mock-integration` and opt-in `real-provider-e2e` wait for **lint-and-syntax** and **unit-tests** to pass first. Gate C does not auto-run on hotspot paths.

---

## Maintainer checklist

- [ ] Runner user in `docker` group
- [ ] `/var/cache/ai-gateway` exists and is writable
- [ ] `CLIPROXY_AUTH_TAR_B64` secret set for Gate C
- [ ] Branch protection required checks match [`.github/BRANCH_PROTECTION_POLICY.md`](../.github/BRANCH_PROTECTION_POLICY.md)
- [ ] Stable stack on `:4000` healthy for post-merge Gate D workflow
- [ ] `scripts/ci/ci-runner-status.sh` shows runner `online` and systemd `active`

---

## Troubleshooting: jobs stuck in `queued`

**Symptom:** `Reminder :: Hotspot Check` passes (GitHub-hosted) but `CI :: Lint and Syntax` / `changes` / `CI :: Build and Unit Test` stay `queued` for minutes.

**Common cause:** the self-hosted runner on `dev-01` is offline or was unregistered. Check:

```bash
scripts/ci/ci-runner-status.sh
# or on the runner host:
sudo systemctl status actions.runner.echoares-lab-ai-gateway.dev-01.service
sudo ls /home/github-runner/actions-runner/.runner   # must exist
```

**Fix (on dev-01):**

```bash
sudo ./scripts/ci/ci-runner-reregister.sh
```

This fetches a repo registration token via `gh`, runs `config.sh --replace`, installs the systemd service, and starts the listener.

**History:** On 2026-06-07 the runner received Ctrl-C, then `config.sh remove` deleted `.runner` without reinstalling the service. CI jobs queued until re-registration.

**Note:** Only one job runs at a time on a single runner; remaining jobs show `queued` until the active job finishes. That is normal — not the same as a dead runner.
