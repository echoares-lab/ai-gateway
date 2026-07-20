# CI/CD Automation Hardening — Epic Breakdown Plan

> **For the executing agent:** This document is not itself a set of GitHub
> issues — it is a ready-to-use specification for creating them. Read
> "How to use this document" below before doing anything else. None of the
> issue numbers referenced in `Bundle:` / `Depends on:` lines exist yet; you
> will create them in the order given and substitute real numbers as you go.

## Context

During a 2026-07-20 session auditing `ai-gateway`'s dependency-alignment and
promotion pipeline, several real, verified bugs were found and fixed:

- A "Promote k3s-01 image pins" pipeline that had been silently failing for
  ~2 days (stale staging pins, a missing `CLIPROXY_CANDIDATE_TAG` secret, and
  a `python3 script.py` vs `python3 -m module` invocation bug).
- A staging deep-smoke `spendlogs` check that always failed because the smoke
  test's fixed prompt collided with gateway-engine's own Redis cache,
  masking the fact that no fresh request ever reached LiteLLM.
- `k3s-01` had zero Renovate/dependency-drift coverage (langfuse ~22 releases
  behind, ClickHouse ~2 major versions behind, MinIO ~6 months behind, none
  of it visible anywhere).
- CLIProxyAPI's `weekly-upstream-track.yml` (which reconstructs a 2-commit
  quota patch stack onto the latest upstream weekly) had never once run,
  because the workflow file only existed on the non-default `echoares/main`
  branch and GitHub only fires `schedule:` triggers for workflows present on
  a repo's **default** branch.

Fixing those surfaced **7 further gaps** that are real and verified but too
large to fix inline — they need proper epic/issue tracking so multiple agents
can pick them up over time using this repo's existing
`docs/process/AGENT_DISPATCH.md` claim → implement → PR → merge → closeout
flow. This document is that breakdown.

## How to use this document

1. For each epic below, run the `gh issue create` command shown in its
   **Epic issue** block, in a repo you have push access to. Note the real
   issue number GitHub assigns.
2. Before creating each epic's children, substitute that real epic number
   into every child's `Bundle: #<EPIC_N_NUMBER>` placeholder, and substitute
   any already-created sibling issue numbers into `Depends on:` /
   `Soft-depends on:` placeholders as you go — create children in the
   `Order` sequence given, lowest first, since later children often
   reference earlier ones.
3. After all epics + children exist, add one `## Next — <short name>`
   section per epic to `docs/ROADMAP.md`, using the templates in
   "ROADMAP.md entries" below (with real issue numbers filled in) — **no
   child issue is claimable by an agent until it is promoted to
   `docs/ROADMAP.md`**, per this repo's standing rule.
4. Dispatch agents against ready (unblocked) children per
   `docs/process/AGENT_DISPATCH.md`. Respect every `Depends on:` /
   `Soft-depends on:` line — several children hard-conflict on the same file
   (see "Cross-epic dependency summary") and must not be worked in parallel.
5. Labels referenced below are this repo's **real, existing** labels
   (verified via `gh label list --limit 200` per repo on 2026-07-20) — do
   not invent new ones. If a repo lacks an ideal label, the closest existing
   one is used and noted inline.

## Cross-epic dependency summary

```text
Epic 1 / Order-1 child "ai-gateway alerting"        ──> Epic 3 / Order-1 child
                                                          (same file: promote-k3s-images.yml)

Epic 1 / Order-1 child "CLIProxyAPI alerting"       ──> Epic 4 / Order-1 child "PAT bundle"
                                                          (same file: weekly-upstream-track.yml)

Epic 1 / Order-2 child "fix Gate D"                 ──> Epic 1 / Order-3 child "real k3s-01 Gate D"
                                                          (settle heartbeat semantics first)

Epic 2 (ArgoCD webhook)                              -- soft-depended-on-by --> Epic 1/Order-3, Epic 5
                                                          (not a hard blocker; just makes both easier)

Epic 5 (pin-mechanism consistency)                   -- soft-depends-on --> Epic 3
                                                          (sequence after to avoid churn, not a file conflict)
```

Two file-level hotspots force **hard** serialization (not just soft
ordering) per `docs/process/REPO_IMPROVEMENT_WORKFLOW.md`'s hotspot-collision
rule:

- `ai-gateway/.github/workflows/promote-k3s-images.yml` — touched by Epic 1's
  ai-gateway alerting child *and* Epic 3's Order-1 child. Epic 3/Order-1 must
  not be claimed until Epic 1's ai-gateway alerting child has merged.
- `CLIProxyAPI/.github/workflows/weekly-upstream-track.yml` — touched by
  Epic 1's CLIProxyAPI alerting child *and* Epic 4's PAT-bundle child. Epic
  4's PAT-bundle child must not be claimed until Epic 1's CLIProxyAPI
  alerting child has merged.

Epic 4's two children (PAT bundle vs. `pr-path-guard.yml` exception) touch
**different** files and are genuinely parallel — both correctly sit at
Order 1 within Epic 4.

---

## Epic 1 — CI/CD failure alerting and honest Gate D signaling

**Repos:** `ai-gateway` + `CLIProxyAPI` + `k3s-01`

### Problem / why now

Zero failure-notification integration exists anywhere in `ai-gateway`'s or
`CLIProxyAPI`'s workflows (verified: `grep -rli "slack\|webhook.*notif\|pushover\|pagerduty\|discord"` across every `.github/workflows/*.yml` in both repos
returns nothing). This is the direct, verified cause of two real incidents
this session: a 2-day staging pin drift that silently broke a promote
pipeline, and a fully-dormant CLIProxyAPI weekly-sync workflow that never
ran once in 3 days. Compounding this, `ai-gateway/.github/workflows/post-merge-gate-d.yml`
runs `on: push: branches: [main]` and hits the **live production edge**
immediately on merge — before anything from that specific merge has actually
reached production (a separate `k3s-01` prod-overlay PR must be reviewed and
merged first, sometimes days later) — and its job carries
`continue-on-error: true`, so even a "production is broken" result shows
green in the PR/commit checklist. Nothing currently tells a human when any
of this breaks; that silence is the root cause worth fixing first.

### Epic issue

```
gh issue create --repo echoares-lab/ai-gateway \
  --title "epic(ops): CI/CD failure alerting and honest Gate D signaling" \
  --label "type:observability" --label "area:infra" --label "priority:high" \
  --body-file - <<'EOF'
## Summary
Add failure notification to the two previously-silent, previously-broken
pipelines (ai-gateway's promote workflow, CLIProxyAPI's weekly upstream
sync), and fix post-merge Gate D so it stops masking real production
failures behind `continue-on-error` and a misleading "post-merge" name.

## Problem
No Slack/webhook/notification integration exists anywhere in ai-gateway or
CLIProxyAPI workflows. This is why a 2-day staging pin drift and a
fully-dormant CLIProxyAPI sync workflow both went unnoticed. Separately,
`post-merge-gate-d.yml` triggers immediately on ai-gateway merge (before
anything has reached prod) and swallows failures via job-level
`continue-on-error: true`.

## Why now
Every other epic in this plan builds more automation on top of these same
pipelines. Wiring alerting first means future breakage in that new
automation gets caught immediately instead of silently, the same way this
session's audit had to catch it by hand.

## Children (atomic; claim these, not this epic)
| Order | Issue | Repo | Deps |
|------:|-------|------|------|
| 1 | Add failure-notification step to `promote-k3s-images.yml` | ai-gateway | none |
| 1 | Add failure-notification step to `weekly-upstream-track.yml` | CLIProxyAPI | none |
| 2 | Fix `post-merge-gate-d.yml` naming/timing/masking | ai-gateway | Soft-depends on Order-1 ai-gateway child |
| 3 | Add a real post-promotion Gate D in k3s-01 | k3s-01 | Depends on Order-2 child |

## Non-goals
- Not building a general-purpose alerting platform — a single webhook
  integration reused across both notification steps is sufficient.
- Not changing what Gate A/B/C validate, only Gate D's trigger semantics and
  failure visibility.

## Acceptance criteria
- Both `promote-k3s-images.yml` and `weekly-upstream-track.yml` post to a
  webhook on job failure, gated behind `if: secrets.<NAME> != ''` so absence
  of the secret is a no-op, not a hard failure.
- `post-merge-gate-d.yml` is renamed or re-documented to accurately describe
  itself as a production-health heartbeat, not a per-merge gate, and no
  longer hides failures behind `continue-on-error` without an explicit
  failure signal reaching a human.
- A real post-*promotion* Gate D exists in k3s-01, firing after a
  prod-overlay PR actually merges and ArgoCD reports the app Synced/Healthy
  at the new revision.

## Risks / rollback notes
Low risk — additive workflow steps. Rollback is reverting the workflow file
changes; no runtime/production behavior changes.

## Suggested labels
`type:observability`, `area:infra`, `priority:high` (ai-gateway has these;
k3s-01/CLIProxyAPI should use `type:reliability` as the closest existing
match if `type:observability` doesn't exist there).

## Execution notes
Parent epic is coordination-only — not claimable. Order-1 children in
different repos are genuinely parallel. Order-2 and Order-3 are strictly
sequential. **Order-1 ai-gateway child hard-blocks Epic 3's Order-1 child**
and **Order-1 CLIProxyAPI child hard-blocks Epic 4's Order-1 child** — both
touch the same workflow files respectively; do not let those race.
EOF
```

### Child issues

**Order 1 — Add failure-notification step to `promote-k3s-images.yml`** (ai-gateway)

```
gh issue create --repo echoares-lab/ai-gateway \
  --title "ci(ops): add failure notification to promote-k3s-images.yml" \
  --label "type:observability" --label "area:infra" --body-file - <<'EOF'
## Summary
Add a job-failure notification step to `promote-k3s-images.yml` so a broken
promote pipeline (staging drift, digest resolution failure, deep-smoke
failure, etc.) is reported to a human instead of sitting silently broken —
this pipeline was silently failing for ~2 days before this session's audit
caught it by hand.

## Scope
- Add a webhook-URL repo secret (name TBD by whoever provisions it, suggest
  `SLACK_WEBHOOK_URL` or similar — this issue does NOT create the secret
  value itself, that must come from a human; see "Execution notes").
- Add an `if: failure()` step (or a dedicated final job with `if: always()`
  checking upstream job results) to `promote-k3s-images.yml` that posts a
  concise failure summary (job name, run URL, git_sha) to the webhook,
  guarded by `if: secrets.SLACK_WEBHOOK_URL != ''` so it's a safe no-op
  until the secret exists.

## Non-goals
- Not building retry logic or auto-remediation — notification only.
- Not touching the workflow's actual promote logic.

## Acceptance criteria
- Workflow YAML parses (`python3 -c "import yaml; yaml.safe_load(open(path))"`).
- Manually verified: forcing a failure (e.g. `workflow_dispatch` with bad
  inputs) triggers the notification step and it doesn't itself error when
  the secret is unset.
- If the webhook secret has not been provisioned by a human by the time this
  is implemented, the PR still merges with the guarded no-op step in place
  and the issue closeout explicitly says "blocked on secret provisioning,
  wiring is in place" rather than claiming full completion.

## Required tests
None beyond YAML validity and a manual dispatch test — this is CI-config-only,
no application code path.

## Dependencies
Bundle: #<EPIC_1_NUMBER>

## Affected files / areas
`.github/workflows/promote-k3s-images.yml`

## Execution notes
**Hard external dependency:** no Slack/Discord/webhook secret exists in this
repo today (verified via grep across all workflow files) — a human must
generate and add it. Do the wiring regardless and leave the guard in place;
do not fabricate a secret or claim the notification is "live" until someone
confirms the secret exists.
EOF
```

**Order 1 — Add failure-notification step to `weekly-upstream-track.yml`** (CLIProxyAPI)

```
gh issue create --repo echoares-lab/CLIProxyAPI \
  --title "ci: add failure notification to weekly-upstream-track.yml" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
Add a job-failure notification step to `weekly-upstream-track.yml` — this
workflow ran completely dormant for its first 3 days of existence (wrong
branch registration bug) with nobody noticing; once fixed, it will still
fail weekly if upstream reconstruction hits a real rebase conflict, and
nothing currently reports that either.

## Scope
- Add (or reuse, if Epic 1's ai-gateway child already provisioned a shared
  webhook secret/app) a webhook-URL secret on this repo.
- Add a failure-notification step covering the `reconstruct` job's
  conflict-abort path specifically (it already has a partial
  `gh issue comment 11` fallback that itself fails with "Resource not
  accessible by integration" due to the same org token-permission issue
  Epic 4 addresses — this notification step should not depend on that
  working).

## Non-goals
- Not fixing the `gh issue comment 11` permission failure itself (that's
  covered by Epic 4's PAT bundle, since it's the same root cause as the
  `gh pr create` failure).

## Acceptance criteria
- Workflow YAML parses.
- Failure path (rebase conflict or any job failure) posts to the webhook
  independent of whether the `gh issue comment` call succeeds.
- Guarded no-op if the secret is unset, same pattern as the ai-gateway child.

## Required tests
Manual: trigger `workflow_dispatch` and verify the notification fires on a
forced failure.

## Dependencies
Bundle: #<EPIC_1_NUMBER>

## Affected files / areas
`.github/workflows/weekly-upstream-track.yml`

## Execution notes
**Hard external dependency:** same as the ai-gateway sibling child — no
webhook secret exists yet, human-provisioned. Can reuse the same Slack
app/channel as the ai-gateway child if convenient (note as a design choice,
not a requirement). **This child hard-blocks Epic 4's Order-1 PAT-bundle
child** — both touch this same file; that child must wait until this one
merges.
EOF
```

**Order 2 — Fix `post-merge-gate-d.yml` naming/timing/masking** (ai-gateway)

```
gh issue create --repo echoares-lab/ai-gateway \
  --title "fix(ci): post-merge-gate-d.yml is a prod-health heartbeat, not a per-merge gate" \
  --label "type:observability" --label "area:infra" --body-file - <<'EOF'
## Summary
`post-merge-gate-d.yml` triggers on every push to `main` and hits the live
production edge (`https://ai.plexplease.com`) immediately — but nothing from
that specific merge has reached production yet (a separate k3s-01
prod-overlay PR must be reviewed and merged first, sometimes days later).
It's actually a production-health heartbeat mislabeled as a post-merge gate,
and its job-level `continue-on-error: true` means even a broken-production
result shows green in the PR/commit checklist.

## Scope
- Rename the workflow (and/or its job/step names, README references, ROADMAP
  mentions) to reflect what it actually is — e.g. "Production Health
  Heartbeat" — OR retarget its trigger so it only fires from a signal that
  actually correlates with a fresh production deploy (harder; see Epic 1's
  Order-3 child for the real fix on the k3s-01 side).
- Remove bare `continue-on-error: true` at the job level; replace with an
  explicit failure-notification step (depends on Order-1 ai-gateway child)
  so failures are visible instead of silently green.

## Non-goals
- Not replacing this workflow's actual health/model/completion checks.
- Not building the "real" post-promotion Gate D here — that's k3s-01's
  Order-3 child; this issue only fixes the existing check's honesty.

## Acceptance criteria
- Workflow's name/comments no longer claim to validate "this merge" reaching
  production.
- A failing check is visible as a failing check in the PR/commit UI (or, at
  minimum, reliably triggers the Order-1 notification step) rather than
  showing green via `continue-on-error`.

## Required tests
Manual: force a failure (e.g. temporarily point `GATEWAY_URL` at an invalid
host via `workflow_dispatch`) and confirm it's now visible as a failure.

## Dependencies
Soft-depends on: Order-1 ai-gateway child (reuses its notification step).
Bundle: #<EPIC_1_NUMBER>

## Affected files / areas
`.github/workflows/post-merge-gate-d.yml`

## Execution notes
Sequential with Order-3 (k3s-01 real Gate D) — settle this workflow's
semantics before building the new one, so they don't end up describing
overlapping things under similar names.
EOF
```

**Order 3 — Add a real post-promotion Gate D in k3s-01**

```
gh issue create --repo echoares-lab/k3s-01 \
  --title "feat(ci): real post-promotion Gate D — validate prod after a prod-overlay merge" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
Add a workflow to k3s-01 that fires after a prod-overlay PR (the ones opened
by ai-gateway's `promote` job) actually merges and ArgoCD reports the `k3s-01`
app Synced/Healthy at the new revision — a genuine "did this promotion
actually land and is prod healthy" check, distinct from ai-gateway's
always-running heartbeat (Epic 1 Order-2).

## Scope
- New workflow, `on: push: branches: [production]` filtered to changes under
  `kubernetes/workloads/home/ai-gateway/overlays/k3s-01/**`, or triggered via
  `repository_dispatch` from the ArgoCD side if that's cleaner.
- Poll (or webhook-trigger, see Epic 2) `argocd app get k3s-01` /
  `kubectl -n argocd get application k3s-01` until Synced/Healthy at the new
  revision (bounded timeout), then run the same class of smoke checks
  ai-gateway's heartbeat runs (health, models, one completion) directly
  against the production edge.
- Wire the Epic 1 failure-notification pattern into this workflow too.

## Non-goals
- Not replacing `scripts/ops/deep-smoke.sh --env prod` if that's still the
  preferred manual/incident tool — this is specifically the automated,
  always-runs-after-a-real-promotion version.

## Acceptance criteria
- Merging a real (test) prod-overlay PR triggers this workflow, it correctly
  waits for ArgoCD to actually reach the new revision (not a stale
  Synced/Healthy from before the merge — check `.status.sync.revision`
  matches, not just `.status.health.status`), and runs smoke checks against
  the actually-updated production.
- Failure is visible (ties to Epic 1's alerting pattern), not masked.

## Required tests
Manual: perform a real (low-risk) prod-overlay promotion and confirm this
workflow fires, waits correctly, and reports pass.

## Dependencies
Depends on: Order-2 ai-gateway child (settle heartbeat semantics first).
Soft-depends on: Epic 2 (ArgoCD webhook) — faster sync detection helps but
polling `argocd app get` works without it.
Bundle: #<EPIC_1_NUMBER>

## Affected files / areas
New file under `.github/workflows/` in k3s-01.

## Execution notes
This is the "close the loop" piece — without it, "did the promotion actually
work" still requires a human to look. Use k3s-01's existing label set
(`type:reliability`, `area:infra` — no `type:observability` label exists on
this repo).
EOF
```

---

## Epic 2 — ArgoCD GitHub webhook for near-real-time sync

**Repo:** `k3s-01` (infra-config; ArgoCD server config lives outside any repo)

### Problem / why now

ArgoCD's reconciliation timeout is 120s (`kubectl -n argocd get cm
argocd-cm -o jsonpath='{.data.timeout\.reconciliation}'`), and no GitHub
webhook is registered (`gh api repos/echoares-lab/k3s-01/hooks` returns an
empty array). Every promotion during this session's audit required manually
forcing sync via `kubectl -n argocd patch application <name> --type merge
-p '{"operation":{"sync":{...}}}'` to get a timely result instead of waiting
up to 2 minutes. This directly slows down every future epic in this plan
that depends on observing a promotion's effect quickly (Epic 1's Order-3
Gate D, Epic 5's migration verification).

### Epic issue

```
gh issue create --repo echoares-lab/k3s-01 \
  --title "epic(infra): ArgoCD GitHub webhook for near-real-time sync" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
Register a GitHub webhook against ArgoCD's `/api/webhook` receiver so git
pushes trigger near-immediate sync instead of waiting on the 120s poll
interval.

## Problem
`kubectl -n argocd get cm argocd-cm` shows `timeout.reconciliation: 120s`,
and `gh api repos/echoares-lab/k3s-01/hooks` is empty — no webhook exists.
Every promotion this session needed a manual force-sync
(`kubectl patch application ... sync`) to avoid a 2-minute wait.

## Why now
This is pure infra config, low-risk, and every other epic that touches a
promotion path benefits from it immediately.

## Children (atomic; claim these, not this epic)
| Order | Issue | Repo | Deps |
|------:|-------|------|------|
| 1 | Register the GitHub webhook + ArgoCD shared secret | k3s-01 | none |
| 2 | Document the webhook in the promotion runbook | k3s-01 | Depends on Order-1 |

## Non-goals
- Not changing ArgoCD's `syncPolicy` (`automated`/`selfHeal`/`prune` stay as
  configured) — only how quickly it notices a change.
- Not removing the 120s poll as a fallback — webhook is additive.

## Acceptance criteria
- `gh api repos/echoares-lab/k3s-01/hooks` shows the registered webhook.
- Observed sync latency after a test commit is materially below 120s
  (single-digit seconds, typically).
- This is **evidence-based acceptance, not "PR merged"** — most of this
  epic's work has no corresponding `git diff` (it's a GitHub API call +
  ArgoCD server config), so closeout must include the actual latency
  observation, not just a merged PR reference.

## Risks / rollback notes
Very low risk — webhooks are additive; removing the webhook registration via
`gh api -X DELETE repos/echoares-lab/k3s-01/hooks/<id>` fully reverts.

## Suggested labels
`type:reliability`, `area:infra` (k3s-01's existing set).

## Execution notes
Parent epic is coordination-only — not claimable. **Hard external
dependency:** requires the ArgoCD server's public/tunnel-reachable URL and
either repo-admin rights to register a GitHub webhook (may exceed an agent's
`gh` auth scope — same class of blocker as the org-policy issues in Epic 4)
or an existing ArgoCD ingress already reachable for webhook delivery. If
admin scope is unavailable, do the prep work (exact `gh api
repos/.../hooks` payload, the `argocd-secret` `webhook.github.secret` value
to set) and leave a clear, actionable TODO rather than claiming completion.
EOF
```

### Child issues

**Order 1 — Register the GitHub webhook + ArgoCD shared secret**

```
gh issue create --repo echoares-lab/k3s-01 \
  --title "feat(infra): register GitHub webhook for ArgoCD sync" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
Register a GitHub webhook on this repo pointed at ArgoCD's `/api/webhook`
endpoint, with a shared secret matching `argocd-secret`'s
`webhook.github.secret` key, so pushes to `production` trigger near-instant
ArgoCD reconciliation instead of waiting on the 120s poll.

## Scope
1. Determine ArgoCD's externally-reachable webhook URL
   (`https://<argocd-host>/api/webhook`).
2. Generate a webhook secret; set it in the `argocd-secret` Kubernetes
   Secret under `webhook.github.secret` (`kubectl -n argocd patch secret
   argocd-secret ...` or via the existing secrets-management path this
   cluster uses — check `externalsecrets.yaml` patterns already in this
   repo for the house style).
3. Register the webhook: `gh api repos/echoares-lab/k3s-01/hooks -X POST
   -f name=web -f active=true -f "events[]=push" -f
   config[url]=<argocd-webhook-url> -f config[content_type]=json -f
   config[secret]=<the-secret>`.
4. Restart/reload `argocd-server` if required to pick up the new secret.

## Non-goals
Not changing which paths/branches ArgoCD watches — only how it learns about
changes.

## Acceptance criteria
- `gh api repos/echoares-lab/k3s-01/hooks` lists the new webhook with
  `active: true`.
- A test commit to `production` triggers ArgoCD sync within a few seconds
  (observe via `kubectl -n argocd get application <app> -w` or repeated
  `argocd app get` calls timestamped around the push) — record the actual
  observed latency in the closeout comment.
- No secret value is committed to git; it only exists in the GitHub webhook
  config and the `argocd-secret` Kubernetes Secret.

## Required tests
The latency observation above IS the test — no unit/integration test suite
applies to this infra change.

## Dependencies
Bundle: #<EPIC_2_NUMBER>

## Affected files / areas
No repo files necessarily change (GitHub API + cluster secret) — if the
`argocd-secret` value needs to be sourced via an ExternalSecret rather than
a direct `kubectl patch`, that would touch a `*-secrets.yaml`/
`externalsecrets.yaml` file; check house style first.

## Execution notes
**Hard external dependency:** needs (a) ArgoCD's public/tunnel URL, which
this issue's author may not have handy — check existing docs/runbooks for
it first — and (b) repo-admin rights on `k3s-01` to register a webhook,
which may exceed an agent's `gh` auth. If blocked, leave the exact `gh api`
command and the ArgoCD secret-setting command as a documented TODO with
`status:blocked`, rather than claiming completion.
EOF
```

**Order 2 — Document the webhook in the promotion runbook**

```
gh issue create --repo echoares-lab/k3s-01 \
  --title "docs(infra): document ArgoCD webhook in promotion runbook" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
Update the promotion runbook/docs to reflect that ArgoCD now syncs via
webhook (near-instant) rather than relying on the 120s poll, and remove or
caveat any existing "manually force sync via kubectl patch" guidance that
was a workaround for the previous lack of a webhook.

## Scope
Find and update whatever doc currently describes the promotion flow (search
for "kubectl patch application" / "force sync" / "reconciliation" across
`docs/` in this repo and in `ai-gateway`'s `docs/ops/DEPENDENCY_UPDATES.md`
and `docs/CICD_PHASE2_CD_K3S.md`/`docs/CICD_PHASE2_STAGING.md`).

## Non-goals
Not writing new architecture docs — updating existing ones only.

## Acceptance criteria
Relevant docs no longer present manual force-sync as the expected/required
step; webhook-triggered near-instant sync is documented as the norm, with
manual force-sync noted only as a fallback if the webhook ever fails.

## Required tests
None — docs-only change.

## Dependencies
Depends on: Order-1 child (webhook must actually exist first).
Bundle: #<EPIC_2_NUMBER>

## Affected files / areas
Documentation only — likely spans both `k3s-01` and `ai-gateway` repos;
open a matching small PR in `ai-gateway` too if `docs/ops/DEPENDENCY_UPDATES.md`
references the old manual-sync pattern.

## Execution notes
Small, low-risk doc cleanup. No serialization concerns.
EOF
```

---

## Epic 3 — Automate litellm/langfuse staging-to-production promotion

**Repos:** `ai-gateway` + `k3s-01`

### Problem / why now

Renovate already opens PRs bumping litellm (`docker-compose.yml`,
`docker-compose.dev.yml`) and langfuse (`docker-compose.yml`) in ai-gateway —
but merging those PRs only updates ai-gateway's **local** compose files.
Nothing propagates the new pin into k3s-01's staging overlay
(`core-workloads.yaml` + `db-jobs.yaml` for litellm's Deployment and
`litellm-migrate` Job; `observability.yaml` for langfuse web+worker) or opens
a prod-overlay promote PR. Both were bumped entirely by hand this session
(staging edit → force ArgoCD sync → verify migrate Job/trace ingestion →
prod edit → force sync → verify). There's an exact, proven precedent to
extend: the `bump-staging`/`promote` jobs already in
`promote-k3s-images.yml`, currently scoped to `gateway-engine`/
`credential-prober`/`docs-server` only.

### Epic issue

```
gh issue create --repo echoares-lab/ai-gateway \
  --title "epic(ops): automate litellm/langfuse staging-to-production promotion" \
  --label "type:reliability" --label "area:infra" --label "priority:high" --body-file - <<'EOF'
## Summary
Extend the existing app-image promote pipeline (`bump-staging`/`promote`
jobs in `promote-k3s-images.yml`) to also cover litellm and langfuse, which
today have Renovate PRs in ai-gateway's own compose files but zero
propagation into k3s-01 staging or production.

## Problem
Both litellm and langfuse prod promotions this session were done entirely by
hand: edit k3s-01 overlay YAML directly, force ArgoCD sync, verify migration
Job / trace ingestion manually, repeat for prod. No automation exists.

## Why now
The `bump-staging`/`promote` job pattern is proven (built and verified twice
this session for the app images) — this is extension work on a known-good
pattern, not new-pattern design.

## Children (atomic; claim these, not this epic)
| Order | Issue | Repo | Deps |
|------:|-------|------|------|
| 1 | Extend `bump-staging` to diff-detect + mirror litellm/langfuse pins into k3s-01 staging | ai-gateway + k3s-01 | Depends on ai-gateway alerting child of Epic 1 (#<EPIC_1_NUMBER>, same file) |
| 2 | Extend `promote` job to open k3s-01 prod PRs for litellm/langfuse | ai-gateway + k3s-01 | Depends on Order-1 (this epic) |

## Non-goals
- Not changing how Renovate detects litellm/langfuse updates in ai-gateway's
  own compose files — only what happens after a bump merges.
- Not auto-merging any prod PR — matches existing "never auto-merge
  high-risk updates" rule.

## Acceptance criteria
- Merging a Renovate PR that bumps litellm's or langfuse's pin in
  `docker-compose.yml` results in the same digest/tag automatically landing
  in k3s-01's staging overlay (both the Deployment and, for litellm, the
  `litellm-migrate` Job) within the same CI run that already handles the app
  images.
- Staging deep-smoke gates the change exactly as it does for app images
  before...
- ...a k3s-01 prod-overlay PR is automatically opened, with the PR body
  explicitly calling out litellm's required gates from
  `docs/ops/DEPENDENCY_UPDATES.md` §LiteLLM (Prisma migration review,
  `litellm-migrate` Job success) rather than treating it identically to the
  app images' simpler promotion.

## Risks / rollback notes
Medium — litellm carries real DB-migration risk (Prisma). The automation
must surface, not hide, the existing manual-review gates; rollback is
reverting the k3s-01 overlay pin, same as any other image (documented
already in `docs/ops/DEPENDENCY_UPDATES.md` §LiteLLM Rollback table).

## Suggested labels
`type:reliability`, `area:infra`, `priority:high`, `risk:medium` (litellm
specifically) — all exist on ai-gateway.

## Execution notes
Parent epic is coordination-only — not claimable. **Order-1 hard-depends on
Epic 1's ai-gateway alerting child** — both touch
`promote-k3s-images.yml`; do not claim Order-1 until that child has merged.
EOF
```

### Child issues

**Order 1 — Extend `bump-staging` to diff-detect + mirror litellm/langfuse pins into k3s-01 staging**

```
gh issue create --repo echoares-lab/ai-gateway \
  --title "feat(ops): mirror litellm/langfuse pin changes into k3s-01 staging automatically" \
  --label "type:reliability" --label "area:infra" --label "risk:medium" --body-file - <<'EOF'
## Summary
Extend the `bump-staging` job in `promote-k3s-images.yml` (currently only
bumps `gateway-engine`/`credential-prober`/`docs-server` to the latest git_sha
on every merge) to also detect and mirror litellm and langfuse pin changes.

## Scope
Unlike the app images (which always bump to "whatever main just built"),
litellm/langfuse are external images whose pins only change when a Renovate
PR merges — so this job needs to **diff `docker-compose.yml` between the
triggering merge commit and its parent** to detect whether the litellm or
langfuse image reference actually changed, and only then mirror that exact
digest/tag into:
- `kubernetes/workloads/home/ai-gateway/overlays/staging/core-workloads.yaml`
  (litellm Deployment) and `db-jobs.yaml` (litellm-migrate Job) in k3s-01 —
  same digest for both, per the existing "web+worker/deployment+migrate
  updated together" convention.
- `kubernetes/workloads/home/ai-gateway/overlays/staging/observability.yaml`
  (langfuse web + worker) in k3s-01 — both images together, matching
  `docs/ops/DEPENDENCY_UPDATES.md` §Langfuse's "web and worker updated
  together" gate.

Reuse the existing bump-staging pattern: push directly to k3s-01
`production` branch (staging tracks fast-moving changes, no PR gate, per
existing convention), wait for ArgoCD rollout, let `staging-deep-smoke` gate
the result.

## Non-goals
Not touching the app-image bump logic already working correctly.

## Acceptance criteria
- A test Renovate-style PR bumping litellm's pin in `docker-compose.yml`,
  once merged to `main`, results in the k3s-01 staging overlay's litellm
  Deployment *and* `litellm-migrate` Job both landing on the new digest in
  the same automated run.
- A test PR bumping langfuse similarly updates both langfuse-web and
  langfuse-worker together in staging.
- A merge that does NOT touch litellm/langfuse in `docker-compose.yml`
  leaves those pins untouched (only the app-image pins bump, as today) —
  this is the critical "diff, don't always-latest" behavior distinguishing
  this from the existing app-image logic.
- `staging-deep-smoke --full` passes after the mirrored bump, including the
  `spendlogs` check (validates the litellm path specifically) if litellm was
  the one bumped.

## Required tests
- Manual: craft a test commit changing only the litellm digest in
  `docker-compose.yml`, merge to a test branch of `main` (or use
  `workflow_dispatch` with a specific git_sha), confirm the diff-detection
  correctly identifies the change and mirrors only that image.
- Full `make test-fast` / existing CI suite must still pass.

## Dependencies
Depends on: Epic 1's ai-gateway alerting child (#<EPIC_1_NUMBER>'s Order-1
ai-gateway child) — same file, must merge first.
Bundle: #<EPIC_3_NUMBER>

## Affected files / areas
`.github/workflows/promote-k3s-images.yml` (ai-gateway); k3s-01's
`kubernetes/workloads/home/ai-gateway/overlays/staging/{core-workloads.yaml,db-jobs.yaml,observability.yaml}`
get written to by the job at runtime (no repo change needed there ahead of
time).

## Execution notes
**Hotspot file** — do not work this in parallel with anything else touching
`promote-k3s-images.yml`. High-value but needs careful testing since a bug
here could push a bad litellm/langfuse pin to staging automatically (staging
deep-smoke is the safety net, same as the existing app-image path).
EOF
```

**Order 2 — Extend `promote` job to open k3s-01 prod PRs for litellm/langfuse**

```
gh issue create --repo echoares-lab/ai-gateway \
  --title "feat(ops): open k3s-01 prod PRs for litellm/langfuse after staging validation" \
  --label "type:reliability" --label "area:infra" --label "risk:medium" --body-file - <<'EOF'
## Summary
Extend the `promote` job in `promote-k3s-images.yml` to open a k3s-01
prod-overlay PR for litellm/langfuse once `staging-deep-smoke` has gated a
mirrored bump from Order-1, mirroring how it already does this for the app
images.

## Scope
- After Order-1's staging mirror + deep-smoke gate passes, if litellm or
  langfuse pins changed, include them in the promote PR's diff (same PR as
  app images if they changed together, or a standalone PR if litellm/langfuse
  changed independently — follow whatever the existing `promote` job's
  diff-detection naturally produces).
- The generated PR body must explicitly restate litellm's required
  pre-promotion gates from `docs/ops/DEPENDENCY_UPDATES.md` §LiteLLM
  (Prisma migration review, confirm `litellm-migrate` succeeded on staging,
  not just "image pin changed") — do not treat litellm identically to the
  simpler app-image promotion, which has no DB-migration risk.
- Never auto-merge — matches every other prod-promote path in this repo.

## Non-goals
Not building a fully separate promote pipeline — extending the existing
`promote` job's diff/PR-body logic.

## Acceptance criteria
- After Order-1 mirrors a litellm change to staging and deep-smoke passes,
  a real k3s-01 prod-overlay PR appears with the litellm digest bump and a
  body section restating the Prisma-migration-review requirement.
- Same for langfuse (web+worker together), with the body restating
  `docs/ops/DEPENDENCY_UPDATES.md` §Langfuse's gates (trace ingestion smoke,
  worker health after deploy).
- PR is never auto-merged.

## Required tests
Manual: drive a litellm and a langfuse test bump through Order-1's staging
mirror, confirm the resulting prod PR appears with correct content and gate
callouts.

## Dependencies
Depends on: Order-1 (this epic).
Bundle: #<EPIC_3_NUMBER>

## Affected files / areas
`.github/workflows/promote-k3s-images.yml`

## Execution notes
Sequential after Order-1 by construction (needs its staging-mirror output to
exist before there's anything to promote).
EOF
```

---

## Epic 4 — CLIProxyAPI weekly upstream-sync automation unblock

**Repo:** `CLIProxyAPI`

### Problem / why now

`weekly-upstream-track.yml`'s `notify-ai-gateway` job would `repository_dispatch`
a `cliproxy-candidate-ready` event straight into ai-gateway's
`promote-k3s-images.yml` (which already listens for exactly that event and
consumes `client_payload.cliproxy_digest`) — fully built on the ai-gateway
side, completely disconnected on the CLIProxyAPI side. Two independent
reasons: `AI_GATEWAY_DISPATCH_TOKEN` doesn't exist as a secret
(`gh api repos/echoares-lab/CLIProxyAPI/actions/secrets` returns empty), and
the workflow's own `gh pr create` step (to open the weekly candidate PR) is
blocked by an org-wide policy (`default_workflow_permissions: "read"`;
`PATCH .../actions/permissions/workflow` returns `409: "Write permissions
for workflows are disabled by the organization"` — confirmed org-admin-only,
not fixable via API by a normal repo collaborator). Separately,
`pr-path-guard.yml`'s `ensure-no-translator-changes` check will fail on
**every future weekly sync PR** by design, since upstream continuously
touches `internal/translator/**` as part of normal development — this
already happened for real (PR #21 this session: 154 files changed, 35 under
`internal/translator/`, check failed, had to be merged through manually
since no branch protection currently enforces required checks on this repo
tier).

### Epic issue

```
gh issue create --repo echoares-lab/CLIProxyAPI \
  --title "epic(ops): CLIProxyAPI weekly upstream-sync automation unblock" \
  --label "type:reliability" --label "area:infra" --label "priority:high" --body-file - <<'EOF'
## Summary
Unblock `weekly-upstream-track.yml`'s two independent failure points (PR
creation blocked by org policy; ai-gateway dispatch never wired) via
PAT-based secrets, and stop `pr-path-guard.yml` from perpetually failing on
every future weekly sync PR.

## Problem
`AI_GATEWAY_DISPATCH_TOKEN` doesn't exist. The workflow's `gh pr create`
step fails because `default_workflow_permissions: "read"` is an org policy,
confirmed not fixable via repo-level API access. `pr-path-guard.yml`
legitimately fails on every weekly sync since upstream continuously touches
the fenced-off `internal/translator/**` path.

## Why now
The rebase mechanism itself was proven clean this session (41 upstream
commits, zero conflicts against the 2-commit quota patch stack) — the only
things stopping this from running unattended weekly are these three
permission/policy issues, all now precisely diagnosed.

## Children (atomic; claim these, not this epic)
| Order | Issue | Repo | Deps |
|------:|-------|------|------|
| 1 | Add PAT secrets for `gh pr create` + `AI_GATEWAY_DISPATCH_TOKEN` | CLIProxyAPI | Depends on Epic 1's CLIProxyAPI alerting child (#<EPIC_1_NUMBER>, same file) |
| 1 | Add `pr-path-guard.yml` exception for automation branches | CLIProxyAPI | none — different file, safe in parallel with the above |

## Non-goals
- Not asking an org admin to change the org-wide workflow-permissions
  policy — the PAT-based workaround avoids needing that entirely (same
  pattern ai-gateway's own `promote-k3s-images.yml` already uses via
  `K3S_GITOPS_TOKEN`/`GH_PAT_AUTO_APPROVE`).
- Not relaxing `pr-path-guard.yml` for anything except the specific
  automation branch pattern.

## Acceptance criteria
- `weekly-upstream-track.yml`'s `gh pr create` step succeeds using a PAT
  instead of the restricted default `GITHUB_TOKEN`.
- The `notify-ai-gateway` job fires a real `repository_dispatch` to
  `echoares-lab/ai-gateway` with the correct `cliproxy-candidate-ready`
  payload shape ai-gateway's `promote-k3s-images.yml` already expects.
- `pr-path-guard.yml` no longer fails PRs from `automation/upstream-candidate-*`
  branches even when they touch `internal/translator/**`.
- Both PAT secrets are human-provisioned — this epic's closeout must
  explicitly state whether they were actually added (not just wired) before
  claiming the dispatch chain is live end-to-end.

## Risks / rollback notes
The PAT needs care: scope it minimally (repo-scoped, not org-wide) and treat
it as sensitive. Rollback is removing the secrets, which reverts the
workflow's PR-creation/dispatch steps to their current (broken) no-op state
— no functional regression risk.

## Suggested labels
`type:reliability`, `area:infra`, `priority:high` (CLIProxyAPI's existing
set — no `type:observability` here).

## Execution notes
Parent epic is coordination-only — not claimable. Order-1's two children
touch different files and are genuinely parallel. The PAT-bundle child
**hard-depends on Epic 1's CLIProxyAPI alerting child** (same file:
`weekly-upstream-track.yml`).
EOF
```

### Child issues

**Order 1 — Add PAT secrets for `gh pr create` + `AI_GATEWAY_DISPATCH_TOKEN`**

```
gh issue create --repo echoares-lab/CLIProxyAPI \
  --title "ci: add PAT secrets to unblock weekly-upstream-track PR creation and ai-gateway dispatch" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
Add two PAT-based secrets so `weekly-upstream-track.yml` can (a) create its
own candidate PRs despite the org's `default_workflow_permissions: "read"`
policy, and (b) actually fire the `cliproxy-candidate-ready`
`repository_dispatch` into ai-gateway.

## Scope
1. A repo-scoped PAT (with `contents:write`, `pull-requests:write` on
   `CLIProxyAPI`) used in place of `${{ github.token }}` specifically for the
   `gh pr create` call in the `reconstruct` job — same pattern as
   `ai-gateway/.github/workflows/promote-k3s-images.yml`'s
   `K3S_GITOPS_TOKEN`/`GH_PAT_AUTO_APPROVE` fallback (`env: PAT: ${{
   secrets.K3S_GITOPS_TOKEN || secrets.GH_PAT_AUTO_APPROVE }}`).
2. `AI_GATEWAY_DISPATCH_TOKEN` — a PAT with `repo` scope on
   `echoares-lab/ai-gateway`, used by the existing (currently dormant)
   `notify-ai-gateway` job's `curl` call to
   `https://api.github.com/repos/echoares-lab/ai-gateway/dispatches`.
3. Verify the dispatch payload shape (`event_type`, `client_payload` keys)
   matches exactly what ai-gateway's `promote-k3s-images.yml` resolve step
   expects for `repository_dispatch` (`DISPATCH_CLIPROXY_TAG`/
   `DISPATCH_CLIPROXY_DIGEST`/`DISPATCH_GIT_SHA` env var sourcing) — read
   that file's `resolve-sha`/`cliproxy` steps to confirm field names line up
   exactly before considering this done.

## Non-goals
Not changing the org's workflow-permissions policy — this sidesteps it
entirely via PAT-based auth, which doesn't require org-admin action.

## Acceptance criteria
- `weekly-upstream-track.yml`'s `gh pr create` step succeeds on a real
  triggered run (verify via a manual `workflow_dispatch`).
- The `notify-ai-gateway` job's `curl` call succeeds (non-error HTTP status)
  and a corresponding `promote-k3s-images.yml` run actually starts on the
  ai-gateway side in response.
- **If the PAT values have not been provided by a human by the time this is
  worked**, the issue closeout must say so explicitly (`status:blocked`,
  wiring complete, secrets pending) rather than claiming the chain is live.

## Required tests
Manual end-to-end: trigger `weekly-upstream-track.yml` via
`workflow_dispatch`, confirm PR creation succeeds, confirm the dispatch
lands and starts a real `promote-k3s-images.yml` run on ai-gateway with the
correct cliproxy digest.

## Dependencies
Depends on: Epic 1's CLIProxyAPI alerting child (#<EPIC_1_NUMBER>'s Order-1
CLIProxyAPI child) — same file, must merge first.
Bundle: #<EPIC_4_NUMBER>

## Affected files / areas
`.github/workflows/weekly-upstream-track.yml` (CLIProxyAPI); read (do not
need to modify unless the payload shape mismatches) `.github/workflows/promote-k3s-images.yml` (ai-gateway).

## Execution notes
**Hard external dependency for both secrets:** a human must generate and
paste real PAT values — not something an agent can self-issue. Do all the
wiring, verify the payload shape matches by reading both workflow files
carefully, and leave an explicit, actionable TODO if the secrets aren't
provided yet. **Hotspot file** — do not work in parallel with anything else
touching `weekly-upstream-track.yml`.
EOF
```

**Order 1 — Add `pr-path-guard.yml` exception for automation branches**

```
gh issue create --repo echoares-lab/CLIProxyAPI \
  --title "ci: exempt automation/upstream-candidate-* branches from translator-path-guard" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
`pr-path-guard.yml`'s `ensure-no-translator-changes` job blocks any PR
touching `internal/translator/**`, intended to gate casual contributor
changes to sensitive maintainer-owned code. Upstream
(`router-for-me/CLIProxyAPI`) continuously touches that directory as part of
normal development, so every weekly `automation/upstream-candidate-*` PR
reconstructing the quota patch stack legitimately includes translator
changes (already reviewed/merged upstream, not new/risky contributor
changes) and will always fail this check. Confirmed on real PR #21 this
session (154 files, 35 under `internal/translator/`).

## Scope
Add a condition to the `ensure-no-translator-changes` job in
`pr-path-guard.yml` (or the whole `translator-path-guard` workflow) to skip
when `github.head_ref` matches `automation/upstream-candidate-*` (or the PR
author is the automation identity, whichever is more robust against branch
renames).

## Non-goals
Not removing the guard for regular contributor PRs — only exempting the
specific automation-generated branch pattern.

## Acceptance criteria
- A test PR from a branch named `automation/upstream-candidate-*` that
  touches `internal/translator/**` passes `ensure-no-translator-changes`.
- A PR from any other branch touching the same path still fails it, exactly
  as today.

## Required tests
Manual: open a test PR from an `automation/upstream-candidate-test` branch
touching a translator file, confirm the check passes; confirm a normal
branch touching the same file still fails.

## Dependencies
Bundle: #<EPIC_4_NUMBER>

## Affected files / areas
`.github/workflows/pr-path-guard.yml`

## Execution notes
Different file from the PAT-bundle child — safe to work in parallel with
it. Low risk, small diff.
EOF
```

---

## Epic 5 — Standardize k3s-01 image-pin mechanism

**Repo:** `k3s-01` (lowest priority in this plan)

### Problem / why now

`gateway-engine`'s kustomize `images:` entry uses `newTag: "<git_sha>"` while
`credential-prober`/`docs-server`/`cli-proxy-api`/`langfuse`/`cpa-manager`
all use `digest: sha256:...`. Before this session, langfuse was also pinned
two *different* ways between staging (raw digest embedded directly in
`observability.yaml`, no kustomize override) and prod (kustomize `images:`
override in `kustomization.yaml`) — now both use the direct-in-manifest
form, but the app images still use kustomize overrides, so two different pin
mechanisms coexist for different images in the same overlay. This makes it
harder for Renovate's newly-added k3s-01 scanning (its `kustomize` manager
understands overrides cleanly; its `kubernetes` manager has to regex-scan
raw YAML) and harder for a human to answer "where do I look for X's current
pin."

### Epic issue

```
gh issue create --repo echoares-lab/k3s-01 \
  --title "epic(infra): standardize k3s-01 image-pin mechanism" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
Audit and standardize on one image-pin mechanism (recommend: kustomize
`images:` digest overrides) across k3s-01's staging and prod ai-gateway
overlays, replacing the current mix of `newTag`, `digest`, and
raw-YAML-embedded-digest approaches.

## Problem
`gateway-engine` uses `newTag`, most others use `digest` via kustomize
overrides, and langfuse was pinned via raw-embedded digests in the manifest
YAML directly (no kustomize override) until this session. Renovate's
`kustomize` manager (clean) vs `kubernetes` manager (regex-scans raw YAML)
track these differently depending on mechanism.

## Why now
Lowest priority in this plan — pure hygiene, no functional bug. Sequence
after Epic 3 to avoid migration-list churn (Epic 3 touches the same overlay
files while wiring litellm/langfuse automation).

## Children (atomic; claim these, not this epic)
| Order | Issue | Repo | Deps |
|------:|-------|------|------|
| 1 | Audit current pin mechanism per image; produce migration list | k3s-01 | none |
| 2 | Migrate holdouts (gateway-engine's `newTag`, any others found) to consistent kustomize digest overrides | k3s-01 | Depends on Order-1 |

## Non-goals
Not changing which images are pinned or to what versions — purely the
mechanism used to express the pin.

## Acceptance criteria
Every ai-gateway-related image in both staging and k3s-01 (prod) overlays
uses the same pin mechanism (kustomize `images:` digest overrides,
recommended since Renovate's `kustomize` manager handles it most cleanly),
consistently across both overlays.

## Risks / rollback notes
Very low — this is a representation change, not a behavior change (the
actual digest/tag being pinned doesn't change during migration, just how
it's expressed). Rollback is trivial (revert the YAML change).

## Suggested labels
`type:reliability`, `area:infra`.

## Execution notes
Parent epic is coordination-only — not claimable. **Soft-depends on Epic 3**
(sequence after to avoid churn — both touch the same overlay files, but this
isn't a strict file conflict like the Epic 1↔3 / Epic 1↔4 hotspots, since
Epic 3's changes are runtime-written by CI, not source-edited).
EOF
```

### Child issues

**Order 1 — Audit current pin mechanism per image; produce migration list**

```
gh issue create --repo echoares-lab/k3s-01 \
  --title "chore(infra): audit image-pin mechanisms across ai-gateway overlays" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
Produce a definitive list of every ai-gateway-related image reference in
both the staging and k3s-01 (prod) overlays, how each is currently pinned
(kustomize `images:` with `digest:`, kustomize `images:` with `newTag:`, or
raw digest embedded directly in the manifest YAML), and a recommended target
mechanism for each.

## Scope
Grep `kubernetes/workloads/home/ai-gateway/overlays/{staging,k3s-01}/**/*.yaml`
for every `image:` line and every `kustomization.yaml` `images:` entry;
tabulate image name, current mechanism, overlay(s) it appears in, and
whether staging/prod are consistent with each other for that image.

## Non-goals
Not migrating anything yet — audit and recommendation only.

## Acceptance criteria
A markdown table (in the issue body or a linked doc) listing every image,
its current pin mechanism(s), and the recommended target — ready for Order-2
to execute against directly.

## Required tests
None — this is a documentation/audit task.

## Dependencies
Bundle: #<EPIC_5_NUMBER>

## Affected files / areas
Read-only audit of `kubernetes/workloads/home/ai-gateway/overlays/**`.

## Execution notes
Small, safe, no serialization concerns beyond the epic-level soft-dependency
on Epic 3.
EOF
```

**Order 2 — Migrate holdouts to consistent kustomize digest overrides**

```
gh issue create --repo echoares-lab/k3s-01 \
  --title "refactor(infra): migrate gateway-engine and other holdouts to kustomize digest overrides" \
  --label "type:reliability" --label "area:infra" --body-file - <<'EOF'
## Summary
Execute the migration list from Order-1: convert `gateway-engine`'s
`newTag:` pin (and any other holdouts the audit found) to `digest:`-based
kustomize `images:` overrides, consistently across staging and k3s-01
(prod) overlays.

## Scope
Per the Order-1 audit's migration list. Note: `gateway-engine`/
`credential-prober`/`docs-server` are currently written at runtime by
ai-gateway's `bump-staging`/`promote` jobs using `newTag: "<git_sha>"` —
changing the target mechanism here means those CI jobs
(`scripts/k3s/promote_k3s_images.py`'s `_set_image_pin` logic) also need a
corresponding update to resolve a digest instead of using the git_sha tag
directly, or the migration will be immediately undone by the next automated
bump. Coordinate this with whoever owns `promote-k3s-images.yml` at
execution time — this may need a small companion ai-gateway PR, not just a
k3s-01 change.

## Non-goals
Not changing which digests/tags are pinned, only the mechanism.

## Acceptance criteria
- Every image from the Order-1 audit uses the target mechanism consistently
  in both overlays.
- A subsequent automated staging bump (from ai-gateway's `bump-staging` job)
  does not revert the migration — verify this explicitly, since that job
  currently writes `newTag:` directly.

## Required tests
- `kubectl kustomize kubernetes/workloads/home/ai-gateway/overlays/{staging,k3s-01}`
  renders cleanly after migration.
- k3s-01's own test suite (`pytest tests/`) passes, including the
  `test_kustomization_pins_candidate_images` test in
  `tests/test_ai_gateway_staging_workloads.py` (already tolerant of both
  `digest`/`newTag` forms as of this session — may need updating again
  depending on the final target mechanism chosen).
- Trigger a real ai-gateway merge after migrating and confirm the next
  automated `bump-staging` run doesn't silently revert the mechanism change.

## Dependencies
Depends on: Order-1 (this epic).
Bundle: #<EPIC_5_NUMBER>

## Affected files / areas
`kubernetes/workloads/home/ai-gateway/overlays/{staging,k3s-01}/kustomization.yaml`
and possibly `ai-gateway/scripts/k3s/promote_k3s_images.py` if the runtime
CI writer needs updating too (cross-repo — flag clearly if so).

## Execution notes
Watch for the "CI immediately reverts this migration" trap described above —
this is the one child in the whole plan most likely to silently regress if
its cross-repo interaction with `promote_k3s_images.py` isn't accounted for.
EOF
```

---

## ROADMAP.md entries

Add one `## Next — <short name>` section per epic to `docs/ai-gateway/docs/ROADMAP.md`
(substituting real issue numbers), following the exact format already used
there (see the "CLIProxy upstream patch and dependency update loop" section
for the closest precedent — a cross-repo epic with a hotspot dependency
called out inline).

```markdown
## Next — CI/CD failure alerting and honest Gate D signaling

Approve coordination epic [#<EPIC_1_NUMBER>](https://github.com/echoares-lab/ai-gateway/issues/<EPIC_1_NUMBER>)
and its four atomic children. Adds failure notification to the two
previously-silent pipelines that caused this session's staging-drift and
dormant-CLIProxyAPI-sync incidents, and fixes Gate D's misleading
naming/timing/masking.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Notify on promote-k3s-images.yml failure #TBD](...) | `ai-gateway` | Ready; blocked on webhook secret provisioning |
| 1 | [Notify on weekly-upstream-track.yml failure #TBD](...) | `CLIProxyAPI` | Ready; blocked on webhook secret provisioning |
| 2 | [Fix Gate D naming/timing/masking #TBD](...) | `ai-gateway` | Depends on Order-1 ai-gateway child |
| 3 | [Real post-promotion Gate D #TBD](...) | `k3s-01` | Depends on Order-2 |

Release invariants:
- parent epic is coordination-only;
- Order-1 ai-gateway child hard-blocks the litellm/langfuse-automation
  epic's Order-1 child (same file: `promote-k3s-images.yml`);
- Order-1 CLIProxyAPI child hard-blocks the CLIProxyAPI-unblock epic's PAT
  child (same file: `weekly-upstream-track.yml`);
- neither webhook secret exists yet — wiring may merge ahead of the secret
  being provisioned; closeouts must say so explicitly.

---

## Next — ArgoCD GitHub webhook for near-real-time sync

Approve coordination epic [#<EPIC_2_NUMBER>](https://github.com/echoares-lab/k3s-01/issues/<EPIC_2_NUMBER>)
and its two atomic children. Replaces ArgoCD's 120s poll interval with
near-instant webhook-triggered sync.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Register GitHub webhook #TBD](...) | `k3s-01` | Ready; may need repo-admin scope beyond agent auth |
| 2 | [Document webhook in runbook #TBD](...) | `k3s-01` | Depends on Order-1 |

Release invariants:
- parent epic is coordination-only;
- acceptance is evidence-based (observed sync latency), not just "PR
  merged" — most of this epic's work has no corresponding git diff.

---

## Next — Automate litellm/langfuse staging-to-production promotion

Approve coordination epic [#<EPIC_3_NUMBER>](https://github.com/echoares-lab/ai-gateway/issues/<EPIC_3_NUMBER>)
and its two atomic children. Extends the proven `bump-staging`/`promote`
pattern (currently app-images-only) to litellm and langfuse.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Mirror litellm/langfuse pins to k3s-01 staging #TBD](...) | `ai-gateway` + `k3s-01` | Blocked on #<EPIC_1_NUMBER>'s Order-1 ai-gateway child (same file) |
| 2 | [Open k3s-01 prod PRs for litellm/langfuse #TBD](...) | `ai-gateway` + `k3s-01` | Depends on Order-1 |

Release invariants:
- parent epic is coordination-only;
- never auto-merge the resulting prod PRs;
- litellm promotion must always restate the Prisma-migration-review gate
  from `docs/ops/DEPENDENCY_UPDATES.md` §LiteLLM, not treat it like the
  simpler app-image path.

---

## Next — CLIProxyAPI weekly upstream-sync automation unblock

Approve coordination epic [#<EPIC_4_NUMBER>](https://github.com/echoares-lab/CLIProxyAPI/issues/<EPIC_4_NUMBER>)
and its two atomic children. Unblocks the weekly fork-sync workflow's PR
creation and its dispatch into ai-gateway's promote pipeline.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [PAT secrets for PR creation + dispatch #TBD](...) | `CLIProxyAPI` | Blocked on #<EPIC_1_NUMBER>'s Order-1 CLIProxyAPI child (same file); also blocked on human-provisioned PAT values |
| 1 | [pr-path-guard exception for automation branches #TBD](...) | `CLIProxyAPI` | Ready; different file, parallel with the above |

Release invariants:
- parent epic is coordination-only;
- PAT secrets are a hard external/human dependency — closeout must state
  explicitly whether they were actually provisioned, not just wired.

---

## Next — Standardize k3s-01 image-pin mechanism

Approve coordination epic [#<EPIC_5_NUMBER>](https://github.com/echoares-lab/k3s-01/issues/<EPIC_5_NUMBER>)
and its two atomic children. Lowest priority in this plan — pure pin-hygiene
cleanup, no functional bug.

| Order | Atomic issue | Repository | State / dependency |
|------:|--------------|------------|--------------------|
| 1 | [Audit pin mechanisms #TBD](...) | `k3s-01` | Ready |
| 2 | [Migrate holdouts to consistent mechanism #TBD](...) | `k3s-01` | Depends on Order-1; soft-depends on Epic 3 landing first |

Release invariants:
- parent epic is coordination-only;
- migrating gateway-engine's pin mechanism may require a companion
  ai-gateway PR to `scripts/k3s/promote_k3s_images.py` so automated bumps
  don't immediately revert the migration — flag this explicitly if hit.
```
