"""Independent verifier repro for the /model/new + /model/delete hot-add worker.

Not part of the target's test suite. Exercises the three acceptance paths via a
real FastAPI TestClient against main.app and inspects raw JSON responses so the
verdict rests on observed behavior, not the target author's own assertions.
"""

from __future__ import annotations

import json
import os
import sys

os.environ.pop("GATEWAY_ENGINE_ADMIN_KEY", None)
os.environ.pop("ADMIN_API_KEY", None)

sys.path.insert(0, os.path.dirname(__file__))
from fastapi.testclient import TestClient  # noqa: E402

import main as t  # noqa: E402
from core.model_registry import ModelRegistryRecord, RegistryLoadResult  # noqa: E402


class FakeStore:
    enabled = True

    def __init__(self):
        self.models = {}

    def list_models(self):
        return RegistryLoadResult(source="postgres:model_registry", registry_available=True, models=list(self.models.values()))

    def get_model(self, model_id):
        return self.models.get(model_id)

    def upsert_model(self, model):
        self.models[model.model_id] = model
        return model

    def hard_delete_model(self, model_id):
        return self.models.pop(model_id, None) is not None


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._p = payload or {"ok": True}
        self.text = ""

    def json(self):
        return self._p


class FakeClient:
    def __init__(self, resp=None, exc=None):
        self.resp = resp or FakeResp()
        self.exc = exc
        self.calls = []

    async def post(self, url, **kw):
        self.calls.append({"url": url, **kw})
        if self.exc is not None:
            raise self.exc
        return self.resp


def show(label, resp):
    print(f"\n=== {label} -> HTTP {resp.status_code} ===")
    print(json.dumps(resp.json(), indent=2))


results = {}


def check(name, cond):
    results[name] = cond
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


# 1) Route registration on the live app
routes = {r.path: getattr(r, "methods", set()) for r in t.app.routes}
print("=== Registered routes on main.app ===")
print("  /model/new:", routes.get("/model/new"))
print("  /model/delete:", routes.get("/model/delete"))
check("route /model/new POST registered", "/model/new" in routes and "POST" in routes["/model/new"])
check("route /model/delete POST registered", "/model/delete" in routes and "POST" in routes["/model/delete"])

# --- Path A: missing admin key -> 503 admin_key_required ---
client = TestClient(t.app)
r = client.post("/model/new", json={"model_id": "gpt-5-4", "upstream_model": "gpt-5.4"})
show("A missing-admin-key /model/new", r)
check("A: status 503", r.status_code == 503)
check("A: code admin_key_required", r.json().get("error", {}).get("code") == "admin_key_required")

# --- Path B: happy path (registry upsert + litellm /model/new POST) ---
store = FakeStore()
fc = FakeClient(resp=FakeResp(200, {"created": True}))
t._model_registry_store = lambda: store
t._client = fc
t.LITELLM = "http://litellm:4000"
os.environ["GATEWAY_ENGINE_ADMIN_KEY"] = "test-admin"
os.environ["LITELLM_MASTER_KEY"] = "litellm-master"
client = TestClient(t.app)
r = client.post("/model/new", headers={"x-admin-key": "test-admin"},
                json={"model_id": "gpt-5-4", "upstream_model": "gpt-5.4", "supports_tools": True})
show("B happy /model/new", r)
b = r.json()
check("B: status 200", r.status_code == 200)
check("B: accepted true", b.get("accepted") is True)
check("B: partial_success false", b.get("partial_success") is False)
check("B: registry upserted", "gpt-5-4" in store.models)
check("B: litellm /model/new called", bool(fc.calls) and fc.calls[0]["url"] == "http://litellm:4000/model/new")
check("B: master key bearer forwarded", bool(fc.calls) and fc.calls[0]["headers"].get("authorization") == "Bearer litellm-master")

# --- Path C: litellm unreachable -> graceful partial success, no 500 ---
store = FakeStore()
fc = FakeClient(exc=RuntimeError("litellm down"))
t._model_registry_store = lambda: store
t._client = fc
client = TestClient(t.app)
r = client.post("/model/new", headers={"x-admin-key": "test-admin"},
                json={"model_id": "gpt-5-4", "upstream_model": "gpt-5.4"})
show("C unreachable /model/new", r)
c = r.json()
check("C: status 200 (no 500)", r.status_code == 200)
check("C: accepted true", c.get("accepted") is True)
check("C: partial_success true", c.get("partial_success") is True)
check("C: litellm_add ok false", c.get("litellm_add", {}).get("ok") is False)
check("C: registry still upserted", "gpt-5-4" in store.models)

# --- Path D: /model/delete symmetric happy path ---
store = FakeStore()
store.upsert_model(ModelRegistryRecord(model_id="gpt-5-4", provider="openai", family="openai",
                                       upstream_model="gpt-5.4", litellm_model="openai/gpt-5.4",
                                       enabled=True, status="UNKNOWN"))
fc = FakeClient(resp=FakeResp(200, {"deleted": True}))
t._model_registry_store = lambda: store
t._client = fc
client = TestClient(t.app)
r = client.post("/model/delete", headers={"x-admin-key": "test-admin"}, json={"model_id": "gpt-5-4"})
show("D happy /model/delete", r)
d = r.json()
check("D: status 200", r.status_code == 200)
check("D: accepted true", d.get("accepted") is True)
check("D: registry removed", "gpt-5-4" not in store.models)
check("D: litellm /model/delete called", bool(fc.calls) and fc.calls[0]["url"] == "http://litellm:4000/model/delete")

print("\n=== SUMMARY ===")
failed = [k for k, v in results.items() if not v]
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("FAILED:", failed)
    sys.exit(1)
print("ALL CHECKS PASSED")
