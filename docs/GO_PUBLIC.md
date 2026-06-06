# Going Public Checklist

Use this checklist before changing `echoares-lab/ai-gateway` repository visibility to **public**.

## Before you flip visibility

### 1. Rotate credentials (if repo was ever private with real defaults)

These values **must not** rely on hardcoded fallbacks in source (removed in `feat/go-public-prep`). If the old defaults were ever used on a live stack, rotate:

| Secret | Where set |
|--------|-----------|
| `LITELLM_MASTER_KEY` | `.env`, LiteLLM DB virtual keys |
| `CLIPROXY_API_KEY` | `.env`, `~/.cliproxy/config.yaml` |
| `CLIPROXY_MANAGEMENT_KEY` | `.env`, cliproxy `remote-management.secret-key` |

Generate new values:

```bash
openssl rand -hex 16 | sed 's/^/sk-/'   # LiteLLM master key
./cliproxy-setup.sh install              # regenerates cliproxy API + management keys
```

### 2. Scan git history

```bash
# Optional: install gitleaks, then:
gitleaks detect --source . --verbose
```

Historical commits may contain old hardcoded defaults. Rotation is sufficient if keys are invalidated.

### 3. Verify no secrets in working tree

```bash
CHECK_ALL=1 bash .githooks/prevent-hardcoded-keys.sh
make lint
make test-unit
```

### 4. GitHub settings (public repo on Free plan)

Public repos get **branch protection** and required status checks on Free. After going public:

1. Apply [`.github/BRANCH_PROTECTION_POLICY.md`](../.github/BRANCH_PROTECTION_POLICY.md) in repo Settings → Branches.
2. Confirm required checks: `lint-and-syntax`, `unit-tests`, `mock-integration`, etc.

### 5. Operational hygiene

- Never commit `.env` (gitignored).
- OAuth tokens stay in `~/.cli-proxy-api/` (host volume, not in repo).
- Use `.env.example` / `.env.op` (1Password refs) for onboarding docs only.

## What was scrubbed for public release

- Hardcoded gateway auth fallbacks removed from `services/translator/main.py`
- Compose management key default → `dev-management-key` (dev-only)
- Personal emails → `@example.com` placeholders in RUNBOOK / admin docs
- Internal host IPs → `gateway-host.example` in docs and scripts
- Production URL in architecture docs → `gateway.example.com`
- Extended secret scan: `.githooks/prevent-hardcoded-keys.sh` + CI + pre-commit

## After going public

- Run Gate D smokes on stable after first public merge.
- Review GitHub **Dependabot** and **secret scanning** alerts (enabled by default on public repos).
