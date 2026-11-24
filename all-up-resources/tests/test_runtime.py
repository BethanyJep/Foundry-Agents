"""Demo 3: the code Caldova owns inside the hosted agent."""
import asyncio
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from _paths import RUNTIME

sys.path.insert(0, str(RUNTIME))
runtime = importlib.import_module("runtime")
sys.path.remove(str(RUNTIME))


class FakeStateStore:
    """In-memory stand-in for azure.ai.agentserver.core.storage.FoundryStateStore,
    following the documented surface: get_or_create, async with, get/create/set_item, ETags."""
    stores = {}

    def __init__(self, name):
        self.name, self.items, self.version = name, {}, 0

    @classmethod
    async def get_or_create(cls, name, **_):
        return cls.stores.setdefault(name, cls(name))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_item(self, key):
        if key not in self.items:
            return None
        value, etag = self.items[key]
        return types.SimpleNamespace(value=json.loads(json.dumps(value)), etag=etag)

    async def create_item(self, key, value):
        if key in self.items:
            raise RuntimeError("409 Conflict")
        self.version += 1
        self.items[key] = (value, f'"{self.version}"')

    async def set_item(self, key, value, if_match=None):
        if key not in self.items or self.items[key][1] != if_match:
            raise RuntimeError("412 Precondition Failed")
        self.version += 1
        self.items[key] = (value, f'"{self.version}"')


def fake_storage_module():
    module = types.ModuleType("azure.ai.agentserver.core.storage")
    module.FoundryStateStore = FakeStateStore
    names = ["azure", "azure.ai", "azure.ai.agentserver", "azure.ai.agentserver.core"]
    return mock.patch.dict(sys.modules, {**{n: types.ModuleType(n) for n in names},
                                         "azure.ai.agentserver.core.storage": module})


def run(coro):
    return asyncio.run(coro)


class PlanToolTests(unittest.TestCase):
    def test_plan_tool_is_compact_and_cited(self):
        plan = runtime.plan_disruption_response()
        self.assertEqual(plan["totals"]["residual_gap"], 1900)
        self.assertEqual(plan["blocked_suppliers"][0]["supplier"], "Northbank")
        self.assertEqual([w["week"] for w in plan["route_shortfalls_if_blocked_suppliers_cleared"]], [3, 4])
        self.assertLess(len(json.dumps(plan)), 12000)

    def test_instructions_keep_the_authority_boundary(self):
        for phrase in ("You recommend; people decide.", "never say it's approved", "No operational action taken."):
            self.assertIn(phrase, runtime.INSTRUCTIONS)
        self.assertIn("error", runtime.get_evidence("NOPE-9"))


class GateAndStoreContract:
    """Behavior every case store must show. Subclasses provide make_store()."""

    def setUp(self):
        self.template = runtime.plan_disruption_response()["proposal_template"]
        self.store = self.make_store()

    def submit(self, weeks=None, case_id="CASE-DISRUPT-001", store=None):
        return run(runtime.submit_recommendation(store or self.store, case_id, weeks or self.template["weeks"],
                                                 self.template["cited_sources"], "test"))

    def test_compliant_submission_is_pending_and_idempotent(self):
        first = self.submit()
        self.assertEqual(first["status"], "pending_human_approval")
        self.assertTrue(first["recorded"])
        self.assertFalse(first["duplicate"])
        again = self.submit()
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["operation_id"], first["operation_id"])
        self.assertEqual(run(self.store.get("CASE-DISRUPT-001"))["submissions"], 1)

    def test_gate_rejects_700_on_cedar_and_records_it(self):
        self.submit()
        weeks = json.loads(json.dumps(self.template["weeks"]))
        weeks[0]["routes"] = {"Cedar": 700, "Birch": 400}
        result = self.submit(weeks)
        self.assertEqual(result["status"], "rejected_by_policy_gate")
        self.assertEqual(result["required_approvals"], [])
        self.assertIn("maximum allocation of 600", result["violations"][0]["violation"])
        case = run(self.store.get("CASE-DISRUPT-001"))
        self.assertEqual([h["status"] for h in case["history"]], ["pending_human_approval", "rejected_by_policy_gate"])

    def test_rejection_does_not_replace_the_standing_recommendation(self):
        self.submit()
        weeks = json.loads(json.dumps(self.template["weeks"]))
        weeks[0]["routes"] = {"Cedar": 700, "Birch": 400}
        self.assertEqual(self.submit(weeks)["status"], "rejected_by_policy_gate")
        case = run(self.store.get("CASE-DISRUPT-001"))
        self.assertEqual(case["status"], "pending_human_approval")
        self.assertEqual(case["last_submission_status"], "rejected_by_policy_gate")
        self.assertEqual(run(self.store.list())[0]["status"], "pending_human_approval")
        self.assertTrue(self.submit()["duplicate"])  # re-filing the compliant plan stays a no-op
        self.assertEqual(run(self.store.get("CASE-DISRUPT-001"))["status"], "pending_human_approval")

    def test_case_with_only_rejections_is_rejected(self):
        weeks = json.loads(json.dumps(self.template["weeks"]))
        weeks[0]["routes"] = {"Cedar": 700, "Birch": 400}
        self.submit(weeks)
        self.assertEqual(run(self.store.get("CASE-DISRUPT-001"))["status"], "rejected_by_policy_gate")

    def test_case_is_visible_to_a_new_store_instance(self):
        self.submit()
        reopened = self.make_store(reuse=True)
        self.assertEqual(run(reopened.list())[0]["status"], "pending_human_approval")

    def test_bad_case_id_is_rejected_without_writing(self):
        result = self.submit(case_id="../etc/passwd")
        self.assertEqual(result["status"], "rejected_by_policy_gate")
        self.assertEqual(run(self.store.list()), [])


class FileStoreTests(GateAndStoreContract, unittest.TestCase):
    def make_store(self, reuse=False):
        if not reuse:
            self.tmp = tempfile.TemporaryDirectory()
            self.addCleanup(self.tmp.cleanup)
        return runtime.FileCaseStore(Path(self.tmp.name))

    def test_ledger_is_append_only(self):
        self.submit()
        self.submit()
        self.assertEqual(len((Path(self.tmp.name) / "ledger.jsonl").read_text().strip().splitlines()), 1)


class FoundryStoreTests(GateAndStoreContract, unittest.TestCase):
    def make_store(self, reuse=False):
        if not reuse:
            FakeStateStore.stores.clear()
            patcher = fake_storage_module()
            patcher.start()
            self.addCleanup(patcher.stop)
        return runtime.FoundryCaseStore()

    def test_writes_case_index_and_ledger_items(self):
        result = self.submit()
        items = FakeStateStore.stores["caldova/cases"].items
        self.assertIn("cases/CASE-DISRUPT-001", items)
        self.assertIn("index", items)
        self.assertIn(f"ledger/{result['operation_id']}", items)
        self.assertEqual(result["storage"], "Foundry state store")

    def test_storage_failure_is_reported_not_hidden(self):
        class Broken(runtime.FileCaseStore):
            async def record(self, *a):
                raise OSError("disk unavailable")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        result = self.submit(store=Broken(Path(tmp.name)))
        self.assertFalse(result["recorded"])
        self.assertIn("Nothing was recorded", result["error"])


class StoreSelectionTests(unittest.TestCase):
    def test_hosted_env_selects_state_store(self):
        with fake_storage_module(), mock.patch.dict(os.environ, {"CALDOVA_CASE_STORE": "foundry"}):
            self.assertIsInstance(runtime.case_store_from_env(), runtime.FoundryCaseStore)

    def test_falls_back_to_file_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"CALDOVA_CASE_STORE": "foundry", "CALDOVA_CASE_DIR": tmp}), \
                mock.patch.dict(sys.modules, {"azure.ai.agentserver.core.storage": None}):
            store = runtime.case_store_from_env()
            self.assertIsInstance(store, runtime.FileCaseStore)
            self.assertIn("session", store.kind)


if __name__ == "__main__":
    unittest.main()
