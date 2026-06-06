# Self-Hosted CI Runner Guide

AI Gateway CI runs on a **single self-hosted runner** with persistent disk. Behavior differs from GitHub-hosted runners: caches survive between jobs, host ports are fixed, and workspace pre-clean is targeted (not full wipe).

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

---

## Concurrency and ports

| Constraint | Reason |
|------------|--------|
| Workflow concurrency `ci-CI Suite-self-hosted` | Single runner; cancel in-progress on new push |
| Job concurrency `ci-docker-host-ports` | Mock + Gate C stacks bind host ports 4010, 4011, 18080 |
| Stable stack `:4000` / `:8080` | Must not collide with CI mock stack |

Only **one** mock-integration or real-provider-e2e stack at a time per runner.

---

## Mock stack volume policy

| Variable | Effect |
|----------|--------|
| `CI_MOCK_FRESH_DB=1` | Drop `aidevmock` Postgres volume before mock stack start (default on PR CI) |
| `CI_MOCK_DOWN_VOLUMES=1` | Same as above — alias used by `scripts/ci-free-mock-host-ports.sh` |

Fresh volumes are slower (re-seed from `db/seed-litellm-mock.sql`) but prevent cross-run DB pollution.

---

## Workspace pre-clean

Jobs use [`.github/actions/pre-clean-self-hosted`](../.github/actions/pre-clean-self-hosted/action.yml) to:

1. Fix ownership on `$GITHUB_WORKSPACE`
2. Remove checkout contents **without** deleting `/var/cache/ai-gateway`

Avoid full `rm -rf` of cache paths between jobs in the same workflow.

---

## Job dependency graph (fast-fail)

```
changes ─┬─► lint-and-syntax ──┬─► mock-integration
         │                     └─► real-provider-e2e (hotspot paths)
         ├─► build-translator ─► unit-tests ──┘
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
