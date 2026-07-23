# Model Registry Lifecycle (Never-Delete) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Advertise discovered models even when probes are transiently unhealthy, attach default cross-family fallbacks until curated ones exist, never hard-delete rows, and auto-retire after 30 days of discovery absence with Prometheus/Alertmanager signals.

**Architecture:** Extend the existing `ModelReconciliationService` and `model_registry` schema with explicit `advertised` / `retired` / `absent_since` fields (legacy `enabled` remains a compatibility shim). Probe health becomes informational for catalog membership; scheduled absence tracking drives retirement; metrics export lifecycle gauges for Alertmanager.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, pytest, Prometheus client, Postgres migrations under `db/migrations/`, existing gateway-engine unit tests beside the code.

## Global Constraints

- Never hard-delete registry rows in normal operations (`DELETE ?hard=true` rejected by default).
- Advertise on first discovery when probe is healthy **or** transient (`rate_limited`, `timeout`, `temporarily_unavailable`, `transient`); do not advertise new rows on `missing` / `missing_model`.
- Already-advertised models must not un-advertise on transient probe failure.
- Curated `policy_metadata.fallbacks` always wins; defaults apply only when curated list is absent; discovery must not wipe curated fallbacks.
- Demand-triggered reconciliation never evaluates the retire timer.
- Auto-retire only after continuous discovery absence ≥ `GATEWAY_ENGINE_MODEL_ABSENCE_RETIRE_DAYS` (default 30).
- Spec: `docs/superpowers/specs/2026-07-23-model-registry-lifecycle-never-delete-design.md`.
- Prefer TDD; run focused pytest under `services/gateway-engine` with the repo venv if present (`../../.venv-ci/bin/python -m pytest` or `python -m pytest`).

## File map

| File | Responsibility |
|------|----------------|
| `db/migrations/005_model_registry_lifecycle.sql` | Add `advertised`, `retired`, `absent_since`; expand status check; backfill from `enabled` |
| `services/gateway-engine/core/model_registry.py` | Record fields, `enabled` shim, render fallbacks defaults, store upsert/disable→retire |
| `services/gateway-engine/core/model_reconciliation.py` | Advertise gate, absence clock, retire on scheduled runs |
| `services/gateway-engine/core/metrics.py` | Lifecycle gauges |
| `services/gateway-engine/core/model_lifecycle_defaults.py` | Default cross-family fallback map helper (new, focused) |
| `services/gateway-engine/api/admin_routes.py` | DELETE retires; reject hard delete; status counts |
| `services/gateway-engine/config.py` + `.env.example` | Absence retire/alert day knobs |
| `services/gateway-engine/main.py` | Wire metric refresh if needed after reconcile |
| `docs/ops/RUNBOOK.md` | Operator notes for retire/absence alerts |
| `docs/openapi/gateway-engine.yaml` | Document new fields / error for hard delete |
| k3s overlays (separate PR if needed) | Ship migration `004` into ConfigMap generators |

---

### Task 1: Schema migration + record fields

**Files:**
- Create: `db/migrations/005_model_registry_lifecycle.sql`
- Modify: `services/gateway-engine/core/model_registry.py` (`ModelRegistryRecord`, upsert SQL)
- Test: `services/gateway-engine/test_gateway_engine_model_registry.py`

**Interfaces:**
- Produces: `ModelRegistryRecord.advertised: bool`, `.retired: bool`, `.absent_since: datetime | None`
- Produces: property or helper `record_enabled(record) -> bool` equivalent to `advertised and not retired`
- Produces: status enum includes `PENDING`, `UNHEALTHY`, `RETIRED` (and retains existing values needed for backfill)

- [ ] **Step 1: Write failing tests** asserting `ModelRegistryRecord` round-trips `advertised`/`retired`/`absent_since`, and that `enabled` on the public model/API shape equals `advertised and not retired`.

```python
def test_registry_record_enabled_shim_matches_advertised_and_not_retired():
    active = ModelRegistryRecord(
        model_id="gpt-5-6-sol",
        provider="openai",
        family="openai",
        upstream_model="gpt-5.6-sol",
        litellm_model="openai/gpt-5.6-sol",
        advertised=True,
        retired=False,
        status="UNHEALTHY",
    )
    assert active.enabled is True

    retired = active.model_copy(update={"retired": True, "advertised": False, "status": "RETIRED"})
    assert retired.enabled is False
```

- [ ] **Step 2: Run RED**

```bash
cd /home/dev/repos/ai-gateway/services/gateway-engine
python -m pytest test_gateway_engine_model_registry.py -k 'enabled_shim or advertised or absent_since' -v
```

Expected: FAIL (fields missing / attribute errors).

- [ ] **Step 3: Add migration** `db/migrations/005_model_registry_lifecycle.sql`:

```sql
\connect litellm

ALTER TABLE model_registry
  ADD COLUMN IF NOT EXISTS advertised boolean,
  ADD COLUMN IF NOT EXISTS retired boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS absent_since timestamptz;

UPDATE model_registry
SET advertised = COALESCE(advertised, enabled),
    retired = CASE WHEN status = 'DISABLED' THEN true ELSE COALESCE(retired, false) END
WHERE advertised IS NULL OR status = 'DISABLED';

ALTER TABLE model_registry
  ALTER COLUMN advertised SET DEFAULT true,
  ALTER COLUMN advertised SET NOT NULL;

-- Expand status check to include PENDING, UNHEALTHY, RETIRED (drop/re-add constraint name as used in prod).
ALTER TABLE model_registry DROP CONSTRAINT IF EXISTS model_registry_status_check;
ALTER TABLE model_registry ADD CONSTRAINT model_registry_status_check
  CHECK (status IN (
    'UNKNOWN', 'PENDING', 'HEALTHY', 'UNHEALTHY', 'DEGRADED', 'CRITICAL', 'DISABLED', 'RETIRED'
  ));

CREATE INDEX IF NOT EXISTS model_registry_advertised_idx ON model_registry (advertised);
CREATE INDEX IF NOT EXISTS model_registry_retired_idx ON model_registry (retired);
CREATE INDEX IF NOT EXISTS model_registry_absent_since_idx ON model_registry (absent_since);
```

Mirror staging `\connect litellm_staging` in the k3s staging overlay copy when shipping ops PR.

- [ ] **Step 4: Update `ModelRegistryRecord` and store upsert/select** to persist the new columns. Keep `enabled` as a computed field or synced column updated on write: `enabled = advertised AND NOT retired` so older SQL indexes remain meaningful.

- [ ] **Step 5: Run GREEN** — repeat the pytest command; expect PASS.

- [ ] **Step 6: Commit**

```bash
git add db/migrations/005_model_registry_lifecycle.sql \
  services/gateway-engine/core/model_registry.py \
  services/gateway-engine/test_gateway_engine_model_registry.py
git commit -m "feat(models): add advertised/retired/absent_since lifecycle columns"
```

---

### Task 2: Advertise-on-transient probe gate

**Files:**
- Modify: `services/gateway-engine/core/model_reconciliation.py` (probe → enabled/advertised block ~617–636)
- Test: `services/gateway-engine/test_gateway_engine_model_reconciliation.py`

**Interfaces:**
- Consumes: `ModelRegistryRecord.advertised`, `.retired`
- Produces: advertise decision helper, e.g. `should_advertise_after_probe(probe_status: str, *, is_new_or_retry: bool, currently_advertised: bool) -> bool`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_rate_limited_new_discovery_is_advertised_and_applied():
    fakes = Fakes(discovered=[{"id": "AI-Gateway:gpt-5.6-sol"}])

    async def rate_limited_probe(model):
        return model.model_copy(
            update={"probe_status": "rate_limited", "status": "UNHEALTHY", "probe_http_status": 429}
        )

    fakes.probe = rate_limited_probe
    result = await fakes.service().run(ReconciliationTrigger.STARTUP)
    assert result.outcome == "success"
    assert result.models[0].advertised is True
    assert result.models[0].enabled is True
    assert "model_name: gpt-5-6-sol" in fakes.applied[-1][0].content


@pytest.mark.asyncio
async def test_missing_model_new_discovery_stays_unadvertised():
    fakes = Fakes(discovered=[{"id": "AI-Gateway:gpt-5.6-sol"}])

    async def missing_probe(model):
        return model.model_copy(
            update={"probe_status": "missing_model", "status": "UNHEALTHY", "probe_http_status": 404}
        )

    fakes.probe = missing_probe
    result = await fakes.service().run(ReconciliationTrigger.STARTUP)
    assert result.models[0].advertised is False
    assert result.verification in {"not_required", "verified"}


@pytest.mark.asyncio
async def test_transient_probe_keeps_already_advertised_model():
    existing = _model(advertised=True, enabled=True, status="HEALTHY", probe_status="healthy", source="cliproxy")
    fakes = Fakes(existing=[existing], discovered=[existing])

    async def transient_probe(model):
        return model.model_copy(update={"probe_status": "rate_limited", "status": "UNHEALTHY"})

    fakes.probe = transient_probe
    result = await fakes.service(probe_is_stale=lambda m: True).run(ReconciliationTrigger.SCHEDULED)
    assert result.models[0].advertised is True
```

Update `_model()` / `Fakes` helpers to set `advertised` consistent with `enabled` for older tests.

- [ ] **Step 2: Run RED** — expect `test_rate_limited_new_discovery_is_advertised_and_applied` to FAIL (today requires healthy).

- [ ] **Step 3: Implement gate** in `_run` probe loop:

```python
_TRANSIENT_PROBE = frozenset({
    "transient", "temporarily_unavailable", "timeout", "rate_limited", "preserve",
})
_MISSING_PROBE = frozenset({"missing", "missing_model"})

def should_advertise_after_probe(probe_status: str, *, currently_advertised: bool) -> bool:
    status = str(probe_status or "").lower()
    if currently_advertised and status not in _MISSING_PROBE:
        return True
    if status == "healthy" or status in _TRANSIENT_PROBE:
        return True
    return False
```

For additions / retryable unadvertised rows, set `advertised = should_advertise_after_probe(...)` and `enabled = advertised and not retired`. Do **not** require `healthy` alone.

- [ ] **Step 4: Adjust** `test_unhealthy_discovered_add_remains_disabled_and_is_not_rendered` — rename/split so hard `unhealthy`/`error` stay unadvertised, while `rate_limited` advertises.

- [ ] **Step 5: Run GREEN** focused reconciliation tests.

- [ ] **Step 6: Commit**

```bash
git add services/gateway-engine/core/model_reconciliation.py \
  services/gateway-engine/test_gateway_engine_model_reconciliation.py
git commit -m "feat(models): advertise models on transient probe failures"
```

---

### Task 3: Default cross-family fallbacks until curated

**Files:**
- Create: `services/gateway-engine/core/model_lifecycle_defaults.py`
- Modify: `services/gateway-engine/core/model_registry.py` (`render_litellm_config_from_registry`)
- Test: `services/gateway-engine/test_gateway_engine_model_registry.py`

**Interfaces:**
- Produces: `default_fallbacks_for(model: ModelRegistryRecord, advertised: list[ModelRegistryRecord]) -> list[str]`
- Render uses curated `policy_metadata["fallbacks"]` when non-empty; else `default_fallbacks_for`

- [ ] **Step 1: Write failing tests**

```python
def test_render_uses_default_cross_family_fallbacks_when_curated_missing():
    gpt = _registry_model("gpt-5-6-sol", family="openai", advertised=True)
    gem = _registry_model("gemini-3-flash", family="gemini", advertised=True)
    claude = _registry_model("claude-sonnet-4-6", family="anthropic", advertised=True)
    rendered = yaml.safe_load(render_litellm_config_from_registry([gpt, gem, claude]))
    fallbacks = rendered["litellm_settings"]["fallbacks"]
    gpt_fb = next(item["gpt-5-6-sol"] for item in fallbacks if "gpt-5-6-sol" in item)
    assert "gemini-3-flash" in gpt_fb
    assert "claude-sonnet-4-6" in gpt_fb


def test_render_prefers_curated_fallbacks_over_defaults():
    gpt = _registry_model(
        "gpt-5-6-sol",
        family="openai",
        advertised=True,
        policy_metadata={"fallbacks": ["claude-opus-4-8"]},
    )
    claude = _registry_model("claude-opus-4-8", family="anthropic", advertised=True)
    gem = _registry_model("gemini-3-flash", family="gemini", advertised=True)
    rendered = yaml.safe_load(render_litellm_config_from_registry([gpt, claude, gem]))
    gpt_fb = next(item["gpt-5-6-sol"] for item in rendered["litellm_settings"]["fallbacks"] if "gpt-5-6-sol" in item)
    assert gpt_fb == ["claude-opus-4-8"]
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement** `default_fallbacks_for`:

```python
# model_lifecycle_defaults.py
_FAMILY_DEFAULT_ORDER = {
    "openai": ["gemini", "anthropic"],
    "anthropic": ["gemini", "openai"],
    "gemini": ["anthropic", "openai"],
}

def default_fallbacks_for(model, advertised_models):
    by_family = {}
    for peer in advertised_models:
        if peer.model_id == model.model_id or peer.retired or not peer.advertised:
            continue
        by_family.setdefault(peer.family, []).append(peer.model_id)
    ordered = []
    for family in _FAMILY_DEFAULT_ORDER.get(model.family, []):
        ordered.extend(sorted(by_family.get(family, [])))
    return ordered
```

Wire into `render_litellm_config_from_registry` replacing same-family-only default branch. Filter curated lists to advertised targets only.

- [ ] **Step 4: Run GREEN**

- [ ] **Step 5: Commit**

```bash
git add services/gateway-engine/core/model_lifecycle_defaults.py \
  services/gateway-engine/core/model_registry.py \
  services/gateway-engine/test_gateway_engine_model_registry.py
git commit -m "feat(models): default cross-family fallbacks until curated exist"
```

---

### Task 4: Absence clock + scheduled auto-retire

**Files:**
- Modify: `services/gateway-engine/config.py`, `.env.example`
- Modify: `services/gateway-engine/core/model_reconciliation.py`
- Test: `services/gateway-engine/test_gateway_engine_model_reconciliation.py`

**Interfaces:**
- Config: `GATEWAY_ENGINE_MODEL_ABSENCE_RETIRE_DAYS: int = 30`
- Config: `GATEWAY_ENGINE_MODEL_ABSENCE_ALERT_PENDING_DAYS: int = 25` (used by metrics/docs; alert rules outside)
- Produces: absence update inside merge phase; retire only when `trigger != DEMAND`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_scheduled_absence_sets_absent_since_but_keeps_advertised():
    existing = _model(model_id="gpt-5-6-sol", advertised=True, source="cliproxy")
    fakes = Fakes(existing=[existing], discovered=[])  # absent from discovery
    result = await fakes.service().run(ReconciliationTrigger.SCHEDULED)
    row = next(m for m in fakes.models if m.model_id == "gpt-5-6-sol")
    assert row.absent_since is not None
    assert row.advertised is True
    assert row.retired is False


@pytest.mark.asyncio
async def test_scheduled_absence_past_retire_days_retires_row():
    old = datetime.now(timezone.utc) - timedelta(days=31)
    existing = _model(model_id="gpt-5-6-sol", advertised=True, absent_since=old, source="cliproxy")
    fakes = Fakes(existing=[existing], discovered=[])
    result = await fakes.service(absence_retire_days=30).run(ReconciliationTrigger.SCHEDULED)
    row = next(m for m in fakes.models if m.model_id == "gpt-5-6-sol")
    assert row.retired is True
    assert row.advertised is False
    assert row.status == "RETIRED"


@pytest.mark.asyncio
async def test_demand_trigger_does_not_retire_on_long_absence():
    old = datetime.now(timezone.utc) - timedelta(days=31)
    existing = _model(model_id="gpt-5-6-sol", advertised=True, absent_since=old, source="cliproxy")
    fakes = Fakes(existing=[existing], discovered=[])
    await fakes.service(absence_retire_days=30).run(ReconciliationTrigger.DEMAND, requested_model="gpt-5-6-sol")
    row = next(m for m in fakes.models if m.model_id == "gpt-5-6-sol")
    assert row.retired is False
    assert row.advertised is True


@pytest.mark.asyncio
async def test_rediscovery_clears_absent_since():
    old = datetime.now(timezone.utc) - timedelta(days=3)
    existing = _model(model_id="gpt-5-6-sol", advertised=True, absent_since=old, source="cliproxy")
    discovered = [existing.model_copy(update={"absent_since": None})]
    fakes = Fakes(existing=[existing], discovered=[{"id": "AI-Gateway:gpt-5.6-sol"}])
    await fakes.service().run(ReconciliationTrigger.SCHEDULED)
    row = next(m for m in fakes.models if m.model_id == "gpt-5-6-sol")
    assert row.absent_since is None
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement** absence handling after discovery merge:

```python
discovered_ids = {m.model_id for m in discovered}
now = datetime.now(timezone.utc)
for model_id, model in list(merged_by_id.items()):
    if model_id in discovered_ids:
        if model.absent_since is not None:
            merged_by_id[model_id] = model.model_copy(update={"absent_since": None})
        continue
    # absent from discovery
    absent_since = model.absent_since or now
    updates = {"absent_since": absent_since}
    if (
        trigger != ReconciliationTrigger.DEMAND
        and not model.retired
        and (now - absent_since).days >= self.absence_retire_days
    ):
        updates.update({"retired": True, "advertised": False, "status": "RETIRED", "enabled": False})
    merged_by_id[model_id] = model.model_copy(update=updates)
```

Wire `absence_retire_days` from config into `ModelReconciliationService.__init__` and `main.py` factory.

- [ ] **Step 4: Document knobs in `.env.example`**

```bash
GATEWAY_ENGINE_MODEL_ABSENCE_RETIRE_DAYS=30
GATEWAY_ENGINE_MODEL_ABSENCE_ALERT_PENDING_DAYS=25
```

- [ ] **Step 5: Run GREEN**

- [ ] **Step 6: Commit**

```bash
git add services/gateway-engine/core/model_reconciliation.py \
  services/gateway-engine/config.py \
  services/gateway-engine/main.py \
  services/gateway-engine/test_gateway_engine_model_reconciliation.py \
  .env.example
git commit -m "feat(models): track absence and auto-retire after 30 days"
```

---

### Task 5: Prometheus lifecycle metrics

**Files:**
- Modify: `services/gateway-engine/core/metrics.py`
- Modify: `services/gateway-engine/core/model_reconciliation.py` or `main.py` (export after successful persist)
- Test: `services/gateway-engine/test_gateway_engine_model_reconciliation.py` (or new `test_gateway_engine_model_lifecycle_metrics.py`)

**Interfaces:**
- Produces: gauges `gateway_model_absent`, `gateway_model_absent_days`, `gateway_model_advertised`, `gateway_model_retired` with labels `model_id`, `family`
- Produces: `record_model_lifecycle(models: list[ModelRegistryRecord]) -> None`

- [ ] **Step 1: Write failing test** that after a reconcile leaving one absent advertised model, `gateway_model_absent` samples include that `model_id` with value 1.0.

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement gauges** (clear/set pattern per reconcile to avoid stale series where practical):

```python
MODEL_ABSENT = Gauge(
    "gateway_model_absent",
    "Model missing from latest CLIProxy discovery",
    ["model_id", "family"],
)
MODEL_ABSENT_DAYS = Gauge(
    "gateway_model_absent_days",
    "Days since continuous discovery absence began",
    ["model_id", "family"],
)
MODEL_ADVERTISED = Gauge(
    "gateway_model_advertised",
    "Model advertised in live catalog",
    ["model_id", "family"],
)
MODEL_RETIRED = Gauge(
    "gateway_model_retired",
    "Model retired (kept in registry, not advertised)",
    ["model_id", "family"],
)
```

Call `record_model_lifecycle` at end of successful reconcile persist.

- [ ] **Step 4: Run GREEN**

- [ ] **Step 5: Commit**

```bash
git add services/gateway-engine/core/metrics.py \
  services/gateway-engine/core/model_reconciliation.py \
  services/gateway-engine/test_gateway_engine_model_reconciliation.py
git commit -m "feat(models): export lifecycle gauges for absence and retire"
```

---

### Task 6: Admin API retire + reject hard delete + status counts

**Files:**
- Modify: `services/gateway-engine/api/admin_routes.py`
- Modify: `services/gateway-engine/core/model_registry.py` (`disable_model` → retire)
- Modify: `docs/openapi/gateway-engine.yaml`
- Test: `services/gateway-engine/test_gateway_engine_model_registry.py`, `test_gateway_engine_admin_api.py`

**Interfaces:**
- `DELETE /admin/models/{id}` → `retired=True`, `advertised=False`, `status=RETIRED`
- `DELETE /admin/models/{id}?hard=true` → HTTP 400/409 with typed error `hard_delete_disabled`
- Admin status reconciliation/model counts include `advertised`, `retired`, `absent` (keep `enabled`/`disabled` aliases)

- [ ] **Step 1: Write failing API tests** for soft DELETE retiring a row and hard DELETE returning typed rejection without removing the row.

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement** — change `disable_model` to set retire flags; short-circuit hard delete path.

- [ ] **Step 4: Update OpenAPI** for the new error and response fields.

- [ ] **Step 5: Run GREEN**

- [ ] **Step 6: Commit**

```bash
git add services/gateway-engine/api/admin_routes.py \
  services/gateway-engine/core/model_registry.py \
  services/gateway-engine/test_gateway_engine_model_registry.py \
  services/gateway-engine/test_gateway_engine_admin_api.py \
  docs/openapi/gateway-engine.yaml
git commit -m "feat(models): retire via admin delete; reject hard deletes"
```

---

### Task 7: Docs + Alertmanager contract + k3s migration ship notes

**Files:**
- Modify: `docs/ops/RUNBOOK.md` (Automatic model reconciliation section)
- Create or note: alert rule snippet in RUNBOOK for observability gitops handoff
- Modify k3s-01 overlays in a **follow-up PR** to include `005_model_registry_lifecycle.sql` (prod + staging `\connect`)

- [ ] **Step 1: Update RUNBOOK** with lifecycle glossary pointer, advertise-on-transient behavior, absence/retire knobs, and example alert intents:

```yaml
# Intent for observability repo — not applied from ai-gateway directly
# GatewayModelAbsent: gateway_model_absent == 1 for >1h; repeat_interval 24h
# GatewayModelPendingRetire: gateway_model_absent_days >= 25
# GatewayModelAutoRetired: gateway_model_retired == 1 and absent transition
```

- [ ] **Step 2: Commit docs**

```bash
git add docs/ops/RUNBOOK.md
git commit -m "docs(models): document never-delete lifecycle and absence alerts"
```

- [ ] **Step 3: Open/note k3s-01 PR** to mount migration 004 into `ai-gateway-migrations` ConfigMaps (staging + prod), mirroring prior status-values migration pattern.

---

### Task 8: Full verification

- [ ] **Step 1: Run**

```bash
cd /home/dev/repos/ai-gateway/services/gateway-engine
python -m pytest test_gateway_engine_model_registry.py test_gateway_engine_model_reconciliation.py test_gateway_engine_admin_api.py -v
```

Expected: PASS

- [ ] **Step 2: Run broader gateway-engine suite if time allows**

```bash
python -m pytest -q
```

- [ ] **Step 3: Manual live checklist (after deploy)**
  - Demand or scheduled reconcile advertises `gpt-5-6-sol` while probe is 429
  - `/v1/models` lists `AI-Gateway:gpt-5-6-sol`
  - Chat/responses no longer returns invalid-model for that id (may fallback)
  - `/metrics` exposes `gateway_model_absent` / `gateway_model_advertised`
  - Admin DELETE retires without removing the Postgres row

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| Advertise on transient probes | Task 2 |
| Defaults until curated fallbacks | Task 3 |
| Never hard-delete / retire instead | Tasks 1, 6 |
| Absence keep advertised + 30d retire | Task 4 |
| Demand never retires | Task 4 |
| Prom gauges + AM intents | Tasks 5, 7 |
| `enabled` compat shim | Tasks 1, 6 |
| RUNBOOK / OpenAPI | Tasks 6, 7 |
| k3s migration ship | Task 7 follow-up |

## Placeholder scan

No TBD/TODO steps; each task includes concrete tests, commands, and commit messages.
