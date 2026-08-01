# Evaluation-driven quality routing contract

**Status:** approved contract for C-RT-2 (#627), contract child #628.
This document defines the data and ordering boundary only. It does not enable
quality routing, write scores, add an endpoint, or change production config.

## Defaults, scope, and rollback

Quality routing is disabled unless the policy profile explicitly opts in with
`policy_json.eval.enabled: true`; the process-level kill switch, when present,
also defaults to `false`. Missing, malformed, stale, or unavailable scores
always roll back to the existing health/cost/YAML ordering. Disabling the flag
must take effect without persisted state or request migration.

Quality reordering is allowed only inside the already eligible candidate set.
Capability, safety, policy allowlist, family-lock, credential-health, and hard
budget gates remain authoritative and cannot be weakened by a quality score.
There is no request-path LLM judge, prompt sampling, or output capture.

## Versioned score record

The contract version is `eval-quality.v1`. An offline producer supplies one
record per `(task_category, model)`:

```json
{
  "version": "eval-quality.v1",
  "task_category": "code_edit",
  "model": "gpt-5-4",
  "score": 0.88,
  "sample_count": 120,
  "confidence": 0.91,
  "observed_at": "2026-08-01T00:00:00Z",
  "window_days": 7
}
```

`score` and `confidence` are finite numbers in `[0, 1]`; `sample_count` is a
non-negative integer; `observed_at` is UTC RFC-3339; and `window_days` is a
positive integer. Unknown fields are ignored. Records failing validation are
discarded as unavailable, never partially applied.

Policy configuration is bounded as follows:

```yaml
eval:
  enabled: false
  min_samples: 50
  window_days: 7
  task_category: auto
  weight_blend: 0.3
  model_scores: {} # populated by a later offline writer
```

The effective category comes from request metadata when present, then the
profile's explicit category, otherwise `chat`. A score is usable only when its
category matches, `sample_count >= min_samples`, its age is no greater than the
smaller of record and config `window_days`, and confidence is valid. The
runtime child must clamp `weight_blend` to `[0, 1]` and reject non-finite values.

## Deterministic layer order

The quality layer is **5b**, after health/adaptive ordering and before cost
tier and the static baseline:

```text
1 capability hard filter
2 policy allowlist
3 affinity family lock
4 rate-limit / credential-health skip
5 health-weighted order
5b eval-quality reorder (optional)
6 budget cost tier
7 YAML baseline safety net
```

The requested model remains first when it is still eligible. The layer may
reorder only scored eligible tail candidates; unscored candidates retain their
relative order after scored candidates. Scores combine health and quality as
`(1 - weight_blend) * health + weight_blend * quality` when health exists, and
use quality alone otherwise. Equal scores preserve the prior order (stable
sort); no random or timestamp tie-breaker is permitted.

## Fail-open and safety matrix

| Condition | Result |
|---|---|
| disabled or no category scores | unchanged prior order |
| missing, stale, low-sample, malformed, or low-confidence record | ignore that record; preserve relative order |
| all records unusable | unchanged prior order |
| candidate filtered by capability/safety/budget | never reintroduced |
| score store unavailable/timeout | unchanged prior order; safe metric only |
| conflicting health/cost signal | quality may reorder within the eligible set; guard gates still win |

No score, prompt, output, credential, tenant identifier, or provider response
may appear in logs or client responses. Errors expose only fixed codes.

## Safe observability and versioning

Allowed audit fields are: contract version, task category, hashed request ID,
count of eligible/scored candidates, whether the layer applied, score age
bucket, bounded duration, and outcome code. Model family may be recorded; raw
prompts and score payloads may not. `rules_applied` uses the stable tag
`eval:quality_reorder` only when at least one valid score changed the order.

Additive fields require new fixtures under the same version. Breaking changes
negotiate a new version and retain the disabled/fail-open behavior for old
records. Offline aggregation, score writing, admin UI, and production
enablement are separate follow-up children.
