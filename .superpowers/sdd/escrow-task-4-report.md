# Escrow Task 4 — gateway documentation report

## Scope completed

- Defined the exact KV-v2 launcher escrow data and metadata paths and documented the
  SHA-256 alias path derivation.
- Added a least-privilege gateway workload policy limited to data
  create/read/update and metadata read/list. Explicitly excluded delete, destroy,
  undelete, sudo, and metadata deletion.
- Documented Kubernetes service-account authentication, the required gateway-engine
  environment references, short-lived workload credentials, and the prohibition on
  root/general-admin/static OpenBao tokens.
- Made staging-first rollout and promotion gating explicit.
- Added a disposable-path policy check proving write/read are allowed and KV version
  deletion and metadata destruction are denied, with operator-only cleanup.
- Added operator procedures for legacy import, pending/incomplete creation repair,
  token and header redaction, and non-destructive GitOps rollback.

## Validation

- `git diff --check` — passed.
- Confirmed all changed Markdown documents have balanced fenced-code delimiters.
- Confirmed every newly referenced repository-relative document exists.

## Deliberately separate work

The authoritative `echoares-lab/k3s-01` service account, OpenBao role/policy
provisioning, and Deployment environment references remain a separate claimed issue,
worktree, reviewed commit, and PR as required by the implementation plan. This commit
does not modify the k3s repository or claim that the runtime deployment is configured.
