"""Offline tests for the web demo (the hosted agent is mocked): python -m unittest discover -s demo3-run-hosted/web-demo -p "test_*.py" -v"""
import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

import server


STEP_GET_CASE = {"tool": "get_case", "args": {"case_id": "CASE-DISRUPT-001"}, "ms": None, "result": {
    "storage": "Foundry state store",
    "case": {"case_id": "CASE-DISRUPT-001", "status": "pending_human_approval", "submissions": 1,
             "updated_at": "2026-11-17T21:00:00+00:00", "history": [{
                 "operation_id": "abc123", "submitted_at": "2026-11-17T21:00:00+00:00",
                 "status": "pending_human_approval", "violations": [], "required_approvals": [],
                 "open_gap_by_week": {"2": 200}, "proposal": {}}]}}}


class DemoServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.state = cls.httpd.RequestHandlerClass.state
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.state.observed.clear()
        self.state.conversations.clear()
        self.state.case_id = "CASE-DISRUPT-001"

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as res:
            return res.status, res.read()

    def post(self, path, body, headers=None):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(),
                                     {"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as err:
            return {"_status": err.code, **json.loads(err.read())}

    def api_state(self):
        return json.loads(self.get("/api/state")[1])

    def test_static_pages_and_state(self):
        for path in ("/", "/app.js", "/style.css"):
            self.assertEqual(self.get(path)[0], 200)
        state = self.api_state()
        self.assertEqual(state["agent"], "caldova-ops-runtime")
        self.assertNotIn("mode", state)
        self.assertEqual(state["cases"], [])
        self.assertEqual(state["plan"]["totals"]["residual_gap"], 1900)

    def test_new_demo_case_is_fresh_and_hides_older_cases(self):
        server._observe(self.state, STEP_GET_CASE)
        self.assertEqual(len(self.api_state()["cases"]), 1)
        fresh = self.post("/api/new-case", {})["case_id"]
        self.assertRegex(fresh, r"^CASE-DEMO-\d{4}-\d{6}$")
        state = self.api_state()
        self.assertEqual((state["default_case"], state["cases"]), (fresh, []))
        server._observe(self.state, STEP_GET_CASE)  # an older case seen later still stays off the panel
        self.assertEqual(self.api_state()["cases"], [])

    def test_ui_has_no_rehearsal_mode(self):
        page = self.get("/")[1].decode() + self.get("/app.js")[1].decode()
        self.assertNotIn("ehearsal", page)

    def test_path_traversal_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/..%2Fserver.py")
        self.assertEqual(ctx.exception.code, 404)

    def test_chat_goes_to_the_hosted_agent_and_fills_the_case_panel(self):
        reply = ({"text": "### Recommendation\nPending.", "total_ms": 5}, [STEP_GET_CASE])
        with mock.patch.object(server, "chat", return_value=reply) as chat:
            out = self.post("/api/chat", {"message": "What was filed?", "session": "1"})
        chat.assert_called_once()
        self.assertEqual(out["steps"][0]["tool"], "get_case")
        # chat() itself records observed cases; mimic it, as the mock bypasses it
        server._observe(self.state, STEP_GET_CASE)
        self.assertEqual(self.api_state()["cases"][0]["status"], "pending_human_approval")

    def test_submit_recommendation_output_updates_the_panel(self):
        step = {"tool": "submit_recommendation", "args": {"weeks": []}, "result": {
            "case_id": "CASE-X", "status": "rejected_by_policy_gate", "recorded": True, "operation_id": "op1",
            "violations": [{"week": 1, "violation": "too much", "sources": ["DIST-001"]}],
            "required_approvals": [], "open_gap_by_week": {}}}
        self.state.case_id = "CASE-X"
        server._observe(self.state, step)
        server._observe(self.state, step)
        case = self.api_state()["cases"][0]
        self.assertEqual((case["case_id"], case["submissions"]), ("CASE-X", 1))

    def test_missing_azure_packages_is_a_clear_error(self):
        with mock.patch.dict("sys.modules", {"azure.ai.projects": None}):
            out = self.post("/api/chat", {"message": "hi"})
        self.assertEqual(out["_status"], 502)
        self.assertIn("azure-ai-projects", out["error"])

    def test_gate_console_is_a_dry_run_on_the_real_gate(self):
        template = self.api_state()["plan"]["template"]
        ok = self.post("/api/propose", {"weeks": template["weeks"], "cited_sources": template["cited_sources"]})
        self.assertEqual(ok["result"]["status"], "pending_human_approval")
        self.assertTrue(ok["result"]["dry_run"])
        weeks = json.loads(json.dumps(template["weeks"]))
        weeks[0]["routes"] = {"Cedar": 700, "Birch": 400}
        weeks[2].update(supplier="Northbank")
        bad = self.post("/api/propose", {"weeks": weeks, "cited_sources": ["DISRUPT-001"]})
        self.assertEqual(bad["result"]["status"], "rejected_by_policy_gate")
        reasons = " ".join(v["violation"] for v in bad["result"]["violations"])
        for expected in ("maximum allocation of 600", "Northbank cannot be committed", "must cite"):
            self.assertIn(expected, reasons)
        self.assertEqual(self.api_state()["cases"], [])

    def test_bad_input_is_a_400_not_a_crash(self):
        self.assertEqual(self.post("/api/propose", {"weeks": "nope"})["_status"], 400)
        self.assertEqual(self.post("/api/propose", {"weeks": [{"week": "x", "units": 1}]})["_status"], 400)
        self.assertEqual(self.post("/api/chat", {"message": " "})["_status"], 400)
        self.assertEqual(self.post("/api/sweep", {})["_status"], 404)

    def test_cross_origin_post_is_refused(self):
        out = self.post("/api/chat", {"message": "hi"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(out["_status"], 403)


if __name__ == "__main__":
    unittest.main()
