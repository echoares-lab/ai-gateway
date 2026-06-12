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

Docker builds use [`.github/actions/build-docker-cached`](../.github/actions/build-docker-cached/action.yml) with scoped GHA cache (`gateway-engine`, `cliproxy-mock`, `policy-engine-mock`). Mock-stack compose images are built via [`scripts/ci-build-mock-services.sh`](../scripts/ci-build-mock-services.sh) with path-filtered skip when the tagged image already exists locally.

---

## Concurrency and ports

### What runs in parallel

| Layer | Group key | Effect |
|-------|-----------|--------|
| Workflow | `ci-CI Suite-<PR number or ref>` | Different PRs (and `main` pushes) run CI concurrently across the dev runner group |
| Fast jobs | (none) | `lint-and-syntax`, `unit-tests`, `build-gateway-engine`, path-filtered jobs fan out to any idle runner |
| Docker jobs | `ci-docker-host-ports` | One mock or Gate C stack at a time globally (port collision guard; `runner.name` is not allowed in job concurrency groups) |

Workflow concurrency is **per ref**: a new push to the same PR cancels the in-progress run for that PR only. Other PRs are unaffected.

### What stays serialized

| Constraint | Reason |
|------------|--------|
| Job concurrency `ci-docker-host-ports` | Mock + Gate C stacks bind fixed host ports 4010, 4011, 18080 |
| Stable stack `:4000` / `:8080` | Must not collide with CI mock stack on the same host |

Only **one** `mock-integration` or `real-provider-e2e` stack at a time across the runner group (workflow-level per-PR concurrency still allows fast jobs to run in parallel).

---

## Mock stack volume policy

| Variable | Effect |
|----------|--------|
| `CI_MOCK_FRESH_DB=1` | Drop `aidevmock` Postgres volume before mock stack start (default on PR CI) |
| `CI_MOCK_DOWN_VOLUMES=1` | Same as above — alias used by `scripts/ci-free-mock-host-ports.sh` |

Fresh volumes are slower (re-seed from `db/seed-litellm-mock.sql`) but prevent cross-run DB pollution.

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
changes ─┬─► lint-and-syntax ──┬─► mock-integration
         │                     └─► real-provider-e2e (hotspot paths)
         ├─► build-gateway-engine ─► unit-tests ──┘
         ├─► credential-prober (path-filtered)
         └─► multi-repo-isolation (path-filtered)
```

Heavy Docker jobs (`mock-integration`, `real-provider-e2e`) wait for **lint-and-syntax** and **unit-tests** to pass first.

---

## Maintainer checklist

- [ ] Runner user in `docker` group
- [ ] `/var/cache/ai-gateway` exists and is writable
- [ ] `CLIPROXY_AUTH_TAR_B64` secret set for Gate C
- [ ] Branch protection required checks match [`.github/BRANCH_PROTECTION_POLICY.md`](../.github/BRANCH_PROTECTION_POLICY.md)
- [ ] Stable stack on `:4000` healthy for post-merge Gate D workflow
- [ ] `scripts/ci-runner-status.sh` shows runner `online` and systemd `active`

---

## Troubleshooting: jobs stuck in `queued`

**Symptom:** `Reminder :: Hotspot Check` passes (GitHub-hosted) but `CI :: Lint and Syntax` / `changes` / `CI :: Build and Unit Test` stay `queued` for minutes.

**Common cause:** the self-hosted runner on `dev-01` is offline or was unregistered. Check:

```bash
scripts/ci-runner-status.sh
# or on the runner host:
sudo systemctl status actions.runner.echoares-lab-ai-gateway.dev-01.service
sudo ls /home/github-runner/actions-runner/.runner   # must exist
```

**Fix (on dev-01):**

```bash
sudo ./scripts/ci-runner-reregister.sh
```

This fetches a repo registration token via `gh`, runs `config.sh --replace`, installs the systemd service, and starts the listener.

**History:** On 2026-06-07 the runner received Ctrl-C, then `config.sh remove` deleted `.runner` without reinstalling the service. CI jobs queued until re-registration.

**Note:** Only one job runs at a time on a single runner; remaining jobs show `queued` until the active job finishes. That is normal — not the same as a dead runner.
