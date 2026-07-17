# cliproxy-fork-subplan — BLOCKED (infrastructure / access)

**Subplanner:** `bc-3a3a4da3-f8be-4563-acbc-e352823010bd`
**Scope:** CLIProxyAPI half of ai-gateway epic #413 — issues #12 (reset onto upstream),
#13 (re-port quota foundation), #11 (weekly upstream track + Nexus candidate).
**Date:** 2026-07-17

This subtree cannot spawn workers or reach its target repository. Evidence below.
`plan.json` in this directory is the ready-to-run decomposition; it needs only a
`CURSOR_API_KEY`, `bun`, and a GitHub credential scoped to `echoares-lab/CLIProxyAPI`.

## Blocker 1 — Target repo `echoares-lab/CLIProxyAPI` is unreachable (404)

```
$ gh repo view echoares-lab/CLIProxyAPI
GraphQL: Could not resolve to a Repository with the name 'echoares-lab/CLIProxyAPI'. (repository)

$ gh api repos/echoares-lab/CLIProxyAPI
{"message":"Not Found","status":"404"}

$ git ls-remote https://x-access-token:<token>@github.com/echoares-lab/CLIProxyAPI
remote: Repository not found.
fatal: repository '.../echoares-lab/CLIProxyAPI/' not found

$ curl -s -o /dev/null -w '%{http_code}' https://api.github.com/repos/echoares-lab/CLIProxyAPI   # unauthenticated
404
```

Org `echoares-lab` exposes only three repos to any accessible credential:
`homelab-gitops`, `ai-gateway`, `Cli-Proxy-API-Management-Center`. There is no
`CLIProxyAPI` repo (the canonical upstream is `router-for-me/CLIProxyAPI`; the
fork referenced by AGENTS.md/CLAUDE.md at `/home/dev/repos/CLIProxyAPI` is not
present on GitHub under this org, or is private and not granted to this install).

Consequence: issues #12/#13/#11 cannot be viewed, claimed, branched, or PR'd — by
this subplanner or by any cloud-agent worker it would spawn (workers inherit the
same GitHub installation-token scope).

## Blocker 2 — GitHub token is scoped to `ai-gateway` only, read-only

```
$ gh api installation/repositories
{"total_count":1,"repository_selection":"selected",
 "repositories":[{"full_name":"echoares-lab/ai-gateway", ...
   "permissions":{"admin":false,"maintain":false,"push":false,"triage":false,"pull":false}}]}
```

The single granted repo is `ai-gateway`, and even there the token reports no
push/triage/pull. This matches the upstream #414 handoff, which hit HTTP 403 on
issue assignment/comment/label mutations. A credential with write access to
`echoares-lab/CLIProxyAPI` is required.

## Blocker 3 — Orchestration runtime is unavailable

- `CURSOR_API_KEY` is unset (env empty; no key file under `~/.cursor`). The
  orchestrate SDK cannot spawn cloud agents without a personal Cursor API key.
- `bun` is not installed (`which bun` fails; only `node`/`npm` present). The
  loop driver `bun cli.ts run <workspace>` cannot execute.

Even if a repo credential existed, this VM cannot fan out workers.

## What unblocks this subtree

1. Grant a GitHub credential with push/issues/PR write on
   `echoares-lab/CLIProxyAPI` (confirm the fork repo exists / is created).
2. Provide `CURSOR_API_KEY` (personal key) and install `bun`.
3. Re-run: `bun <orchestrate>/scripts/cli.ts run .orchestrate/cliproxy-fork-subplan`.
   The committed `plan.json` already encodes #12→#13→#11 in dependency order with
   verifiers and inlined design contracts (workers cannot see the ai-gateway
   design doc, so the disposition table and per-issue acceptance are inlined).
