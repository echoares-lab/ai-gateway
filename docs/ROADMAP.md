# Roadmap Status

Approved coordination decisions for work that agents may claim. Implementation
follows [the repo-improvement workflow](process/REPO_IMPROVEMENT_WORKFLOW.md):
claim approved, unassigned, atomic issues only. Do not claim coordination epics,
pull requests, closed issues, or items that appear only in
[FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md).

| Doc | Role |
|-----|------|
| **This file** | Approved Now / Next / Parked / Completed work |
| [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) | Unapproved ideas; not claimable until promoted here and given atomic issues |

Last reviewed: 2026-07-31.

## Now

No approved, unassigned atomic issues are currently available to claim. The
latest approved reliability and documentation waves are recorded under
Completed below.

## Next

No work is approved for Next. Promote a candidate only after an explicit roadmap
decision and creation of ready, atomic GitHub issues.

## Parked

No approved parked work. See [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md)
for the unapproved inventory.

## Completed

The following work is closed. Issue links are tracking/coordination records;
pull-request links are implementation evidence. A pull request is never an
atomic issue to claim.

### Staging promotion and nightly integration reliability

The reliability objective in coordination epic
[#504](https://github.com/echoares-lab/ai-gateway/issues/504) is complete.
The parent issue remains open only for final coordination closeout; its children
are closed and must not be reclaimed.

| Completed scope | Closed tracking issue | Implementation evidence |
|-----------------|-----------------------|-------------------------|
| Staging deep-smoke SpendLogs selector after CNPG rename | [#505](https://github.com/echoares-lab/ai-gateway/issues/505) | [PR #503](https://github.com/echoares-lab/ai-gateway/pull/503) |
| Docker Compose v2 provisioning for Nightly Integration | [#506](https://github.com/echoares-lab/ai-gateway/issues/506) | [PR #507](https://github.com/echoares-lab/ai-gateway/pull/507) |
| Nightly runner Python dependency and PATH provisioning | [#511](https://github.com/echoares-lab/ai-gateway/issues/511) | [PR #512](https://github.com/echoares-lab/ai-gateway/pull/512) |
| Nightly pytest selector argument correction | [#513](https://github.com/echoares-lab/ai-gateway/issues/513) | [PR #514](https://github.com/echoares-lab/ai-gateway/pull/514) |

Closeout evidence: [Nightly Integration run
30640621745](https://github.com/echoares-lab/ai-gateway/actions/runs/30640621745)
completed successfully, including Compose installation, Python environment
setup, the Gate C smoke subset, and the full integration matrix.

### Release, routing, and deep-smoke foundations

| Completed scope | Closed tracking issues | Implementation evidence |
|-----------------|------------------------|-------------------------|
| Release identity and versioning | [#379](https://github.com/echoares-lab/ai-gateway/issues/379), [#380](https://github.com/echoares-lab/ai-gateway/issues/380) | [PR #383](https://github.com/echoares-lab/ai-gateway/pull/383) |
| OAuth quota status reporting | [epic #345](https://github.com/echoares-lab/ai-gateway/issues/345), [#347](https://github.com/echoares-lab/ai-gateway/issues/347), [#348](https://github.com/echoares-lab/ai-gateway/issues/348) | [PR #349](https://github.com/echoares-lab/ai-gateway/pull/349), [PR #373](https://github.com/echoares-lab/ai-gateway/pull/373) |
| Gemini CLI retirement and quota reliability | [epic #386](https://github.com/echoares-lab/ai-gateway/issues/386), [#387](https://github.com/echoares-lab/ai-gateway/issues/387), [#388](https://github.com/echoares-lab/ai-gateway/issues/388) | [PR #391](https://github.com/echoares-lab/ai-gateway/pull/391), [PR #394](https://github.com/echoares-lab/ai-gateway/pull/394) |
| Staging deep-smoke promote gate | [epic #396](https://github.com/echoares-lab/ai-gateway/issues/396), [#397–#403](https://github.com/echoares-lab/ai-gateway/issues/397), [#410](https://github.com/echoares-lab/ai-gateway/issues/410) | [PR #404](https://github.com/echoares-lab/ai-gateway/pull/404), [PR #405](https://github.com/echoares-lab/ai-gateway/pull/405), [PR #407](https://github.com/echoares-lab/ai-gateway/pull/407), [PR #409](https://github.com/echoares-lab/ai-gateway/pull/409), [PR #411](https://github.com/echoares-lab/ai-gateway/pull/411), [PR #412](https://github.com/echoares-lab/ai-gateway/pull/412) |

The deep-smoke gate remains the promotion contract: default to staging,
validate API shapes, streaming, quota, cluster readiness, and SpendLogs; do
not replace the advisory production-health heartbeat.

### Dependency, promotion, and infrastructure automation

| Completed scope | Closed tracking issues | Implementation evidence |
|-----------------|------------------------|-------------------------|
| CLIProxy upstream patch, promotion, and rollback loop | [epic #413](https://github.com/echoares-lab/ai-gateway/issues/413), [#414–#419](https://github.com/echoares-lab/ai-gateway/issues/414) | [PR #420](https://github.com/echoares-lab/ai-gateway/pull/420), [PR #421](https://github.com/echoares-lab/ai-gateway/pull/421), [PR #422](https://github.com/echoares-lab/ai-gateway/pull/422), [PR #423](https://github.com/echoares-lab/ai-gateway/pull/423), [PR #424](https://github.com/echoares-lab/ai-gateway/pull/424), [PR #425](https://github.com/echoares-lab/ai-gateway/pull/425) |
| CI/CD alerting and accurate production-health signaling | [epic #468](https://github.com/echoares-lab/ai-gateway/issues/468), [#470](https://github.com/echoares-lab/ai-gateway/issues/470), [#471](https://github.com/echoares-lab/ai-gateway/issues/471) | [PR #475](https://github.com/echoares-lab/ai-gateway/pull/475), [PR #477](https://github.com/echoares-lab/ai-gateway/pull/477), [PR #502](https://github.com/echoares-lab/ai-gateway/pull/502) |
| LiteLLM/Langfuse staging-to-production promotion | [epic #469](https://github.com/echoares-lab/ai-gateway/issues/469), [#472](https://github.com/echoares-lab/ai-gateway/issues/472), [#473](https://github.com/echoares-lab/ai-gateway/issues/473) | [PR #478](https://github.com/echoares-lab/ai-gateway/pull/478), [PR #479](https://github.com/echoares-lab/ai-gateway/pull/479), [PR #480](https://github.com/echoares-lab/ai-gateway/pull/480) |
| ArgoCD GitHub webhook and image-pin standardization | [`k3s-01` epics #100](https://github.com/echoares-lab/k3s-01/issues/100), [#101](https://github.com/echoares-lab/k3s-01/issues/101), [children #102–#106](https://github.com/echoares-lab/k3s-01/issues/102) | Closed in `k3s-01`; consult its merged-PR history |
| CLIProxyAPI weekly upstream-sync unblock | [`CLIProxyAPI` epic #23](https://github.com/echoares-lab/CLIProxyAPI/issues/23), [children #24–#26](https://github.com/echoares-lab/CLIProxyAPI/issues/24) | Closed in `CLIProxyAPI`; consult its merged-PR history |

### Delivered capability work

| Completed scope | Implementation evidence | Note |
|-----------------|-------------------------|------|
| Cross-model tool-use and protocol benchmark | [PR #440](https://github.com/echoares-lab/ai-gateway/pull/440), [PR #484](https://github.com/echoares-lab/ai-gateway/pull/484) | The old references #420–#423 were merged PRs for unrelated CLIProxy work, not a benchmark epic or atomic issues. |
| Model metadata and reasoning normalization | [PR #486](https://github.com/echoares-lab/ai-gateway/pull/486) | The old references #486–#488 were pull requests, not issue numbers. |
| Context-window pruning and expanded Ruff coverage | [PR #487](https://github.com/echoares-lab/ai-gateway/pull/487) | The old references #489–#491 were pull requests, not issue numbers. |

### Earlier completed themes

- [Stability Foundation PR #377](https://github.com/echoares-lab/ai-gateway/pull/377)
  completed the documented CI/config/request-path hardening wave.
- Production cutover and durability work (observability, k3s cutover, Gate D,
  storage, backup, and image-promotion tracks) is closed; development stacks
  remain local tooling and production is k3s only.
- The [Policy Engine and Routing Refactor #38](https://github.com/echoares-lab/ai-gateway/issues/38)
  is implemented in-process under `services/gateway-engine/core/policy/`.

Future work in any completed area requires a newly promoted candidate and new
atomic issue; do not reopen closed epics in place.

## Related docs

- [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md) — unapproved inventory
- [CICD_PHASE2_CD_K3S.md](./CICD_PHASE2_CD_K3S.md)
- [CICD_PHASE2_STAGING.md](./CICD_PHASE2_STAGING.md)
- [Repo Improvement Workflow](process/REPO_IMPROVEMENT_WORKFLOW.md)
