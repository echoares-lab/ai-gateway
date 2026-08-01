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

Last reviewed: 2026-08-01.

## Now

### Faster local mock iteration

Coordination epic [#643](https://github.com/echoares-lab/ai-gateway/issues/643)
(C-AUD-9) is approved to preserve the in-memory Gate B path, add focused
local pytest selection, and prevent clean-db or mock-stack overhead from
returning.

| Delivery order | Tracking issue | Status / dependency |
|----------------|----------------|---------------------|
| 1. Guard focused in-memory mock iteration | [#644](https://github.com/echoares-lab/ai-gateway/issues/644) | `status:blocked`; becomes ready after this promotion merges and Gate D passes |

Scope is limited to an optional `MOCK_TEST_ARGS` selector, an offline Make
dry-run contract, and Obsidian usage/closeout notes. The default
`make test-mock` remains the complete Gate B suite. No Docker, Compose,
database, dev-slot, runtime, API, marker, membership, or CI-filter changes
are permitted.

## Next

No approved next epic. Promote a candidate into this roadmap and create a
ready contract child before claiming new work.

## Parked

No approved parked work. See [FEATURE_CANDIDATES.md](./FEATURE_CANDIDATES.md)
for the unapproved inventory.

## Completed

### Unified configuration snapshot API

Coordination epic [#634](https://github.com/echoares-lab/ai-gateway/issues/634)
(C-SVC-4) and its three serialized children are closed and
production-verified. The delivered `GET /admin/config` endpoint remains
read-only and disabled by default.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Unified config snapshot contract and deterministic fixtures | [#635](https://github.com/echoares-lab/ai-gateway/issues/635) | [PR #639](https://github.com/echoares-lab/ai-gateway/pull/639); heartbeat [30682651614](https://github.com/echoares-lab/ai-gateway/actions/runs/30682651614) |
| Bounded, redacted unified config snapshot builder | [#636](https://github.com/echoares-lab/ai-gateway/issues/636) | [PR #640](https://github.com/echoares-lab/ai-gateway/pull/640); heartbeat [30683294105](https://github.com/echoares-lab/ai-gateway/actions/runs/30683294105) |
| Guarded unified config snapshot API | [#637](https://github.com/echoares-lab/ai-gateway/issues/637) | [PR #641](https://github.com/echoares-lab/ai-gateway/pull/641); heartbeat [30685917747](https://github.com/echoares-lab/ai-gateway/actions/runs/30685917747) |

### Evaluation-driven quality routing

Coordination epic [#627](https://github.com/echoares-lab/ai-gateway/issues/627)
(C-RT-2) and its serialized children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Evaluation-driven quality routing contract and fixtures | [#628](https://github.com/echoares-lab/ai-gateway/issues/628) | [PR #630](https://github.com/echoares-lab/ai-gateway/pull/630); heartbeat [30681163463](https://github.com/echoares-lab/ai-gateway/actions/runs/30681163463) |
| Fail-open quality reorder runtime layer | [#631](https://github.com/echoares-lab/ai-gateway/issues/631) | [PR #632](https://github.com/echoares-lab/ai-gateway/pull/632); heartbeat [30681419295](https://github.com/echoares-lab/ai-gateway/actions/runs/30681419295) |

### Codex WebSocket frame translation

Coordination epic [#621](https://github.com/echoares-lab/ai-gateway/issues/621)
(C-RT-5) and its serialized children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Codex WebSocket translation contract and fixtures | [#622](https://github.com/echoares-lab/ai-gateway/issues/622) | [PR #624](https://github.com/echoares-lab/ai-gateway/pull/624); heartbeat [30679340037](https://github.com/echoares-lab/ai-gateway/actions/runs/30679340037) |
| Opt-in Codex WebSocket frame translator | [#625](https://github.com/echoares-lab/ai-gateway/issues/625) | [PR #626](https://github.com/echoares-lab/ai-gateway/pull/626); heartbeat [30679854952](https://github.com/echoares-lab/ai-gateway/actions/runs/30679854952) |

### MCP visibility and local tool hosting

Coordination epic [#601](https://github.com/echoares-lab/ai-gateway/issues/601)
(C-RT-4) and its three serialized children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| MCP visibility and local tool-hosting contract | [#602](https://github.com/echoares-lab/ai-gateway/issues/602) | [PR #604](https://github.com/echoares-lab/ai-gateway/pull/604); heartbeat [30676607560](https://github.com/echoares-lab/ai-gateway/actions/runs/30676607560) |
| Opt-in HTTP MCP visibility enforcement | [#605](https://github.com/echoares-lab/ai-gateway/issues/605) | [PR #606](https://github.com/echoares-lab/ai-gateway/pull/606); heartbeat [30676958148](https://github.com/echoares-lab/ai-gateway/actions/runs/30676958148) |
| Isolated local MCP tool-host boundary | [#607](https://github.com/echoares-lab/ai-gateway/issues/607) | [PR #608](https://github.com/echoares-lab/ai-gateway/pull/608); heartbeat [30677455796](https://github.com/echoares-lab/ai-gateway/actions/runs/30677455796) |

### CLIProxy management API

Coordination epic [#609](https://github.com/echoares-lab/ai-gateway/issues/609)
(C-SVC-1) and both serialized children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| CLIProxy management API contract and fixtures | [#610](https://github.com/echoares-lab/ai-gateway/issues/610) | [PR #612](https://github.com/echoares-lab/ai-gateway/pull/612); heartbeat [30677758671](https://github.com/echoares-lab/ai-gateway/actions/runs/30677758671) |
| Read-only CLIProxy status adapter | [#613](https://github.com/echoares-lab/ai-gateway/issues/613) | [PR #614](https://github.com/echoares-lab/ai-gateway/pull/614); heartbeat [30678251118](https://github.com/echoares-lab/ai-gateway/actions/runs/30678251118) |

### Client configuration generation service

Coordination epic [#615](https://github.com/echoares-lab/ai-gateway/issues/615)
(C-SVC-2) and both serialized children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Client config generation contract and fixtures | [#616](https://github.com/echoares-lab/ai-gateway/issues/616) | [PR #618](https://github.com/echoares-lab/ai-gateway/pull/618); heartbeat [30678655091](https://github.com/echoares-lab/ai-gateway/actions/runs/30678655091) |
| Bounded client config generation API | [#619](https://github.com/echoares-lab/ai-gateway/issues/619) | [PR #620](https://github.com/echoares-lab/ai-gateway/pull/620); heartbeat [30678932061](https://github.com/echoares-lab/ai-gateway/actions/runs/30678932061) |

### Deeper policy enforcement and WebSocket parity

Coordination epic [#591](https://github.com/echoares-lab/ai-gateway/issues/591)
(C-RT-3) and its three serialized children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Strict policy and WebSocket parity contract | [#592](https://github.com/echoares-lab/ai-gateway/issues/592) | [PR #598](https://github.com/echoares-lab/ai-gateway/pull/598); heartbeat [30675178289](https://github.com/echoares-lab/ai-gateway/actions/runs/30675178289) |
| Strict policy enforcement on HTTP protocol paths | [#593](https://github.com/echoares-lab/ai-gateway/issues/593) | [PR #599](https://github.com/echoares-lab/ai-gateway/pull/599); heartbeat [30675754637](https://github.com/echoares-lab/ai-gateway/actions/runs/30675754637) |
| Opt-in Codex WebSocket policy parity | [#594](https://github.com/echoares-lab/ai-gateway/issues/594) | [PR #600](https://github.com/echoares-lab/ai-gateway/pull/600); heartbeat [30676124241](https://github.com/echoares-lab/ai-gateway/actions/runs/30676124241) |

### Policy hook extraction

Coordination epic [#586](https://github.com/echoares-lab/ai-gateway/issues/586)
(C-AUD-8) and both sequenced children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Policy hook extraction contract and regression matrix | [#587](https://github.com/echoares-lab/ai-gateway/issues/587) | [PR #589](https://github.com/echoares-lab/ai-gateway/pull/589); heartbeat [30674347708](https://github.com/echoares-lab/ai-gateway/actions/runs/30674347708) |
| Injectable request-path policy hook boundary | [#590](https://github.com/echoares-lab/ai-gateway/issues/590) | [PR #596](https://github.com/echoares-lab/ai-gateway/pull/596); heartbeat [30674825464](https://github.com/echoares-lab/ai-gateway/actions/runs/30674825464) |

### Adaptive routing runtime

Coordination epic [#579](https://github.com/echoares-lab/ai-gateway/issues/579)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Adaptive routing signal and fallback contract | [#580](https://github.com/echoares-lab/ai-gateway/issues/580) | [PR #583](https://github.com/echoares-lab/ai-gateway/pull/583); heartbeat [30666469221](https://github.com/echoares-lab/ai-gateway/actions/runs/30666469221) |
| Passive signal capture and adaptive fallback integration | [#581](https://github.com/echoares-lab/ai-gateway/issues/581) | [PR #584](https://github.com/echoares-lab/ai-gateway/pull/584); heartbeat [30666813132](https://github.com/echoares-lab/ai-gateway/actions/runs/30666813132) |

### Model discovery orchestration

Coordination epic [#573](https://github.com/echoares-lab/ai-gateway/issues/573)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Discovery reconciliation contract | [#574](https://github.com/echoares-lab/ai-gateway/issues/574) | [PR #577](https://github.com/echoares-lab/ai-gateway/pull/577); heartbeat [30665533191](https://github.com/echoares-lab/ai-gateway/actions/runs/30665533191) |
| Discovery probe safety in reconcile loop | [#575](https://github.com/echoares-lab/ai-gateway/issues/575) | [PR #578](https://github.com/echoares-lab/ai-gateway/pull/578); heartbeat [30665951010](https://github.com/echoares-lab/ai-gateway/actions/runs/30665951010) |

### Credential remediation orchestration

Coordination epic [#567](https://github.com/echoares-lab/ai-gateway/issues/567)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Remediation API safety contract | [#568](https://github.com/echoares-lab/ai-gateway/issues/568) | [PR #571](https://github.com/echoares-lab/ai-gateway/pull/571); heartbeat [30664479910](https://github.com/echoares-lab/ai-gateway/actions/runs/30664479910) |
| Operator remediation workflow | [#569](https://github.com/echoares-lab/ai-gateway/issues/569) | [PR #572](https://github.com/echoares-lab/ai-gateway/pull/572); heartbeat [30665126234](https://github.com/echoares-lab/ai-gateway/actions/runs/30665126234) |

### Multi-account credential balancing

Coordination epic [#563](https://github.com/echoares-lab/ai-gateway/issues/563)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Deterministic balancing contract | [#561](https://github.com/echoares-lab/ai-gateway/issues/561) | [PR #565](https://github.com/echoares-lab/ai-gateway/pull/565); heartbeat [30663637706](https://github.com/echoares-lab/ai-gateway/actions/runs/30663637706) |
| Safe credential remapping | [#562](https://github.com/echoares-lab/ai-gateway/issues/562) | [PR #566](https://github.com/echoares-lab/ai-gateway/pull/566); heartbeat [30663947138](https://github.com/echoares-lab/ai-gateway/actions/runs/30663947138) |

### Credential pool health orchestration

Coordination epic [#555](https://github.com/echoares-lab/ai-gateway/issues/555)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Pool health state machine contract | [#556](https://github.com/echoares-lab/ai-gateway/issues/556) | [PR #559](https://github.com/echoares-lab/ai-gateway/pull/559); heartbeat [30662836816](https://github.com/echoares-lab/ai-gateway/actions/runs/30662836816) |
| Idempotent reconciliation and alerts | [#557](https://github.com/echoares-lab/ai-gateway/issues/557) | [PR #560](https://github.com/echoares-lab/ai-gateway/pull/560); heartbeat [30663131569](https://github.com/echoares-lab/ai-gateway/actions/runs/30663131569) |

The following work is closed. Issue links are tracking/coordination records;
pull-request links are implementation evidence. A pull request is never an
atomic issue to claim.

### Gateway exception-boundary reliability

Coordination epic [#531](https://github.com/echoares-lab/ai-gateway/issues/531)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Broad-exception inventory and caller contracts | [#532](https://github.com/echoares-lab/ai-gateway/issues/532) | [PR #535](https://github.com/echoares-lab/ai-gateway/pull/535); heartbeat [30653165974](https://github.com/echoares-lab/ai-gateway/actions/runs/30653165974) |
| Typed request-boundary exception handling | [#533](https://github.com/echoares-lab/ai-gateway/issues/533) | [PR #536](https://github.com/echoares-lab/ai-gateway/pull/536); heartbeat [30653519978](https://github.com/echoares-lab/ai-gateway/actions/runs/30653519978) |

### Catch-all proxy edge-case reliability

Coordination epic [#537](https://github.com/echoares-lab/ai-gateway/issues/537)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Upstream failure matrix | [#538](https://github.com/echoares-lab/ai-gateway/issues/538) | [PR #541](https://github.com/echoares-lab/ai-gateway/pull/541); heartbeat [30654046452](https://github.com/echoares-lab/ai-gateway/actions/runs/30654046452) |
| Protocol edge-case response contracts | [#539](https://github.com/echoares-lab/ai-gateway/issues/539) | [PR #542](https://github.com/echoares-lab/ai-gateway/pull/542); heartbeat [30654315255](https://github.com/echoares-lab/ai-gateway/actions/runs/30654315255) |

### WebSocket policy parity

Coordination epic [#543](https://github.com/echoares-lab/ai-gateway/issues/543)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| WebSocket parity contract matrix | [#544](https://github.com/echoares-lab/ai-gateway/issues/544) | [PR #547](https://github.com/echoares-lab/ai-gateway/pull/547); heartbeat [30654805922](https://github.com/echoares-lab/ai-gateway/actions/runs/30654805922) |
| Flagged WebSocket policy denial enforcement | [#545](https://github.com/echoares-lab/ai-gateway/issues/545) | [PR #548](https://github.com/echoares-lab/ai-gateway/pull/548); heartbeat [30655210051](https://github.com/echoares-lab/ai-gateway/actions/runs/30655210051) |

### Staging/config release channels

Coordination epic [#549](https://github.com/echoares-lab/ai-gateway/issues/549)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Config artifact promotion contract | [#550](https://github.com/echoares-lab/ai-gateway/issues/550) | [PR #553](https://github.com/echoares-lab/ai-gateway/pull/553); heartbeat [30662055776](https://github.com/echoares-lab/ai-gateway/actions/runs/30662055776) |
| Staging-to-production promotion gate | [#551](https://github.com/echoares-lab/ai-gateway/issues/551) | [PR #554](https://github.com/echoares-lab/ai-gateway/pull/554); heartbeat [30662324829](https://github.com/echoares-lab/ai-gateway/actions/runs/30662324829) |

### Staging promotion and nightly integration reliability

The reliability objective in coordination epic
[#504](https://github.com/echoares-lab/ai-gateway/issues/504) is complete and
closed. Its children are closed and must not be reclaimed.

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

### Production safety and configuration drift controls

Coordination epic [#517](https://github.com/echoares-lab/ai-gateway/issues/517)
and all children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Explicit Langfuse/Redis production secret contract | [#518](https://github.com/echoares-lab/ai-gateway/issues/518) | [PR #522](https://github.com/echoares-lab/ai-gateway/pull/522); heartbeat [30650538102](https://github.com/echoares-lab/ai-gateway/actions/runs/30650538102) |
| Admin endpoint exposure inventory and validator | [#519](https://github.com/echoares-lab/ai-gateway/issues/519) | [PR #523](https://github.com/echoares-lab/ai-gateway/pull/523); heartbeat [30651011729](https://github.com/echoares-lab/ai-gateway/actions/runs/30651011729) |
| LiteLLM YAML/Postgres precedence and drift fixtures | [#520](https://github.com/echoares-lab/ai-gateway/issues/520) | [PR #524](https://github.com/echoares-lab/ai-gateway/pull/524); heartbeat [30651439607](https://github.com/echoares-lab/ai-gateway/actions/runs/30651439607) |

Closeout evidence: required CI and Gate D passed for each child; the parent
epic was closed after the complete dependency chain was verified.

### Dev-environment compose collision prevention

Coordination epic [#525](https://github.com/echoares-lab/ai-gateway/issues/525)
and both children are closed and production-verified.

| Completed scope | Closed issue | Implementation evidence |
|-----------------|--------------|-------------------------|
| Slot/project ownership preflight | [#526](https://github.com/echoares-lab/ai-gateway/issues/526) | [PR #529](https://github.com/echoares-lab/ai-gateway/pull/529); heartbeat [30652129692](https://github.com/echoares-lab/ai-gateway/actions/runs/30652129692) |
| Startup/list integration and recovery docs | [#527](https://github.com/echoares-lab/ai-gateway/issues/527) | [PR #530](https://github.com/echoares-lab/ai-gateway/pull/530); heartbeat [30652584788](https://github.com/echoares-lab/ai-gateway/actions/runs/30652584788) |

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
